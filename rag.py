import os
import yaml
import cohere
from cohere.errors import BadRequestError
import time
from colorama import Fore, Style
from langchain_community.document_loaders.pdf import PDFPlumberLoader
from langchain_experimental.text_splitter import SemanticChunker
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import Docx2txtLoader, UnstructuredExcelLoader, TextLoader, UnstructuredHTMLLoader, UnstructuredPowerPointLoader, PythonLoader
from langchain_community.vectorstores import FAISS
import chromadb
from langchain_chroma import Chroma
from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter
from langchain_cohere import CohereEmbeddings
from dotenv import load_dotenv
import json
from copy import copy


load_dotenv()

def timeit(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{Fore.GREEN}Function {func.__name__} took {end-start} seconds{Style.RESET_ALL}")
        return result
    return wrapper

def clean_text(text:str):
    text = text.replace("\n", " ").replace("\r", " ").strip()
    # remove any symbols (like bullets) that are not part of the text
    text = text.encode('ascii', 'ignore').decode()

    return text



class MyRAGModel:


    def __init__(self, topic, config, yaml_file=None, model_family=None):
        self.yaml_file = yaml_file
        self.model_family = model_family
        self.model_name = config.get('model_name')
        self.CHANNELS = config.get('channels')

        self.rerank_model = config.get('rerank_model')
        self.chat_model = config['chat_model']
        self.COHERE_API_KEY = config.get('cohere_api_key').format(COHERE_API_KEY=os.getenv("COHERE_API_KEY")) if config.get('cohere_api_key') else None
        
        self.embedder = self._initialize_component(config['embedder'])
        self.text_splitter = self._initialize_component(config['text_splitter'])
        
        self.vector_db_path = config.get("vector_db_path")
        self.chroma_persistent_client = chromadb.PersistentClient(path=self.vector_db_path)

        self.collection = None
        self.user = None
        self.topic = topic
        if not self.topic:
            pass
        else:
            self.collection_name = f"{topic}Collection"
            self.collection = self.chroma_persistent_client.get_or_create_collection(self.collection_name)
            self.vectorstore = Chroma(persist_directory=self.vector_db_path, collection_name=self.collection_name, embedding_function=self.embedder)
            print("Vectorstore loaded!")
            self.retriever = self.vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 20})

        self.co = cohere.Client(self.COHERE_API_KEY)
        self.prompt = config.get('prompt')
        self.original_prompt = copy(self.prompt)
        self.chat_history = []
        """
        example: [
                    {"role": "USER", "text": "Hey, my name is Michael!"},
                    {"role": "CHATBOT", "text": "Hey Michael! How can I help you today?"},
                ]
        """
    
    def __str__(self):
        return f"Running RAG model: {self.model_name} with vectorstore: {self.vector_db_path}"
    
    def _initialize_component(self, component_config):
        component_class = globals()[component_config['class']]
        return component_class(**component_config['params'])

    def _update_yaml(self, channel):
        # Load the YAML file
        with open(self.yaml_file, 'r') as file:
            data = yaml.safe_load(file)
        # Ensure we are working with the correct dictionary structure
        model_config = data['models'][self.model_family][self.model_name]        
        # Update the channels in the YAML file
        model_config['channels'].append(channel)        
        # Write the updated YAML file
        with open(self.yaml_file, 'w') as file:
            yaml.dump(data, file, default_flow_style=False)


        
    def add_channel(self, channel):
        # Add the channel to the list in the class
        if channel not in self.CHANNELS:
            self.CHANNELS.append(channel)
            self._update_yaml(channel)
        self.set_topic(channel)

    def set_topic(self, topic):
        # format the topic to be lowercase and without spaces
        topic = str(topic).lower().replace(" ", "_")
        # replace any special characters with an underscore
        topic = "".join([char if char.isalnum() else "_" for char in topic])
        self.topic = topic
        prompt_expertize = json.load(open("prompts.json", "r")).get(topic)
        if prompt_expertize:
            self.prompt = self.original_prompt.format(expertise=prompt_expertize, query="{query}")  
        else:
            # remove the {expertise} placeholder
            self.prompt = self.original_prompt.format(expertise="", query="{query}")
        self.collection_name = f"{topic}Collection"
        self.collection = self.chroma_persistent_client.get_or_create_collection(self.collection_name)
        self.vectorstore = Chroma(persist_directory=self.vector_db_path, collection_name=self.collection_name, embedding_function=self.embedder)
        self.retriever = self.vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 20})
        
    def set_user(self, user):
        self.user = user

    @timeit
    def load_document(self, path):
        if path.endswith(".docx") or path.endswith(".doc"):
            loader = Docx2txtLoader(file_path=path)
        elif path.endswith(".pdf"):
            loader = PDFPlumberLoader(file_path=path, )
        elif path.endswith(".xlsx") or path.endswith(".xls"):
            loader = UnstructuredExcelLoader(file_path=path)
        elif path.endswith(".txt"):
            loader = TextLoader(file_path=path)
        elif path.endswith(".html"):
            loader = UnstructuredHTMLLoader(file_path=path)
        elif path.endswith(".pptx"):
            loader = UnstructuredPowerPointLoader(file_path=path)
        elif path.endswith(".py"):
            loader = PythonLoader(file_path=path)
        return loader.load()
    
    @timeit
    def split_text(self, document):
        splitted_document = self.text_splitter.split_documents(document)
        return splitted_document
    
    @timeit
    def add_document_to_vectorstore(self, splitted_document):
        if not self.collection:
            print(f"Creating collection for topic {self.topic}...")
            self.collection_name = f"{self.topic}Collection"
            self.collection = self.chroma_persistent_client.get_or_create_collection(self.collection_name)
            self.vectorstore = Chroma.from_documents(documents=splitted_document, embedding=self.embedder, persist_directory=self.vector_db_path, collection_name=f"{self.topic}Collection")
            self.retriever = self.vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 20})
        else:
            self.vectorstore.add_documents(splitted_document)
        

    @timeit
    def retrieve_documents(self, query):
        if self.vectorstore:
            docs = self.retriever.invoke(query)
            with open("retrieved_docs.txt", "w", encoding="utf-8") as f:
                for doc in docs:
                    f.write(f"{doc.metadata}\n")
                    f.write(f"{doc.page_content}\n")
                    f.write("\n")
            prompt_docs = [{"title": doc.metadata.get('source'), "snippet":clean_text(doc.page_content)} for doc in docs]
            sources = [{"source": doc.metadata.get('source'), "page": doc.metadata.get('page'), "file_path": doc.metadata.get('file_path')} for doc in docs]
            # format sources - sources with same "source", should be grouped together
            updated_sources = {}
            for source in sources:
                source_name = source["source"]
                if source_name not in updated_sources:
                    updated_sources[source_name] = dict()
                    # find all pages with the same source
                    pages = []
                    for s in sources:
                        if s["source"] == source_name:
                            if s['page'] == None:
                                continue    
                            pages.append(s["page"])
                    updated_sources[source_name]["pages"] = sorted(pages)
                    updated_sources[source_name]["file_path"] = s["file_path"]
            sources = updated_sources
        else:
            prompt_docs = []
            sources = []
        return prompt_docs, sources
    
    def update_chat_history(self, role, text):
        self.chat_history.append({"role": role, "text": text})
    
    @timeit
    def generate_response(self, query, include_citations=False):
        self.update_chat_history("USER", query)
        docs, sources = self.retrieve_documents(query)
        query = self.prompt.format(user=self.user, query=query)

        # rearank the documents based on the query
        if docs:
            results = self.co.rerank(query=query, documents=docs, model=self.rerank_model, 
                                    rank_fields=["title", "snippet"],
                                    return_documents=True) # this returns a sorted list of documents based on the relevance to the query

            docs = []
            for res in results.dict()['results']:
                docs.append(res['document'])

        response = self.co.chat(message=query, model=self.chat_model, documents=docs, chat_history=self.chat_history[:-1])
        self.update_chat_history("CHATBOT", response.text)
        if include_citations:
            updated_sources = {}
            for source in sources:
                source_name = source["source"]
                if source_name not in updated_sources:
                    updated_sources[source_name] = set()
                updated_sources[source_name].add(source["page"])
            updated_sources = {source: sorted(list(pages)) for source, pages in updated_sources.items()}
            response = {"response": response, "sources": updated_sources}
        return response
    
    @timeit
    def generate_stream_response(self, query, include_citations=False, search_web=False):
        self.update_chat_history("USER", query)

        if search_web:
            connectors =[{"id":"web-search","options":{"site":"arxiv.org"}}]
            query = self.prompt.format(user=self.user, query=query)
            whole_answer = ""
            docs = []
            sources = {}
        else:
            docs, sources = self.retrieve_documents(query)
            query = self.prompt.format(user=self.user, query=query)
             # rearank the documents based on the query
            if docs:
                results = self.co.rerank(query=query, documents=docs, model=self.rerank_model, 
                                        rank_fields=["title", "snippet"],
                                        return_documents=True, 
                                        top_n=5) # this returns a sorted list of documents based on the relevance to the query

                docs = []
                for res in results.dict()['results']:
                    docs.append(res['document'])
            whole_answer = ""
            connectors = []

        try:
            for event in self.co.chat_stream(message=query, model=self.chat_model, chat_history=self.chat_history[:-1], 
                                            documents=docs, temperature=0.4, connectors=connectors):
                if event.event_type == "text-generation":
                    whole_answer += event.text
                    yield event.text
                elif event.event_type == "stream-end":
                    yield "response_end"
                    if sources:
                        yield sources
                    break
        except BadRequestError as e:
            # this is raised when chat history lacks an answer. So we will delete the last 2 messages (user and chatbot messages) and try again
            print(f"Error: {e}")
            # pop the last two messages before the last one
            self.chat_history = self.chat_history[:-3] + self.chat_history[-1:] # this keeps the first x messages up until the -3 index and the last message
            self.generate_stream_response(query, include_citations, search_web)


        self.update_chat_history("CHATBOT", whole_answer)


def my_rag_model_constructor(loader, node):
    return loader.construct_mapping(node, deep=True)
        
yaml.add_constructor('!LunaModel', my_rag_model_constructor, Loader=yaml.FullLoader)
yaml.add_constructor('!LunaModel', my_rag_model_constructor, Loader=yaml.SafeLoader)

def load_model_from_yaml(yaml_file, model_family, model_version):
    with open(yaml_file, 'r') as file:
        config = yaml.load(file, Loader=yaml.FullLoader)
    # Return the model configuration dictionary instead of an instance of MyRAGModel
    return config['models'][model_family][model_version]

# Functions to import and use in another script
def get_model_version(yaml_file, model_family, model_version) -> MyRAGModel:
    config = load_model_from_yaml(yaml_file, model_family, model_version)
    return MyRAGModel(topic=config.get('topic'), config=config, yaml_file=yaml_file, model_family=model_family)