import os
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


    def __init__(self, topic=None):
        self.CHANNELS = ['general','vrp', 'python']

        self.rerank_model = 'rerank-multilingual-v3.0'
        self.chat_model = "command-r-plus" 
        self.COHERE_API_KEY = os.getenv("COHERE_API_KEY")
        self.embedder = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

        self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=0)
        self.chroma_persistent_client = chromadb.PersistentClient(path="./chroma_db")

        self.collection = None
        self.user = None
        self.topic = topic
        if not self.topic:
            pass
        else:
            self.collection_name = f"{topic}Collection"
            self.collection = self.chroma_persistent_client.get_or_create_collection(self.collection_name)
            self.vectorstore = Chroma(persist_directory="./chroma_db", collection_name=self.collection_name, embedding_function=self.embedder)
            print("Vectorstore loaded!")
            self.retriever = self.vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 20})

        self.co = cohere.Client(self.COHERE_API_KEY)
        self.prompt = """
        You are a conversational A.I. assistant named "Luna". 
        {expertise}\n
        Your purpose is to answer user queries based on the context provided.\n
        Answer to what you are asked as detailed as possible. Answer only in an HTML format and no other format.\n
        All your answers should be casted in a well formated HTML syntax, however you don't need to include the initial <html>, <body> and <head> tags.\n
        You should provide your answer inside a <p> tag. If the user asks for sources, also provide the links in <a> tags.\n
        If you need to add a title to your answer, use a <h1> or <h2> tag.\n
        Use <ul> and <li> tags for lists or bullet point, <b> tag for bold text, <i> tag for italic text and <a> tags for links.\n 
        Your answer must be at least 100 words long.\n
        Do not use any Markdown syntax or hashtags.\n
        If you don't know the answer, say that you don't have enough information to answer the question and don't improvise.\n

        User Question: {query}\n
        """
        self.original_prompt = copy(self.prompt)
        self.chat_history = []
        """
        example: [
                    {"role": "USER", "text": "Hey, my name is Michael!"},
                    {"role": "CHATBOT", "text": "Hey Michael! How can I help you today?"},
                ]
        """

    def add_channel(self, channel):
        self.CHANNELS.append(channel)
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
        self.vectorstore = Chroma(persist_directory="./chroma_db", collection_name=self.collection_name, embedding_function=self.embedder)
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
            self.vectorstore = Chroma.from_documents(documents=splitted_document, embedding=self.embedder, persist_directory="./chroma_db", collection_name=f"{self.topic}Collection")
            self.retriever = self.vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 20})
        else:
            self.vectorstore.add_documents(splitted_document)
        

    @timeit
    def retrieve_documents(self, query):
        if self.vectorstore:
            docs = self.retriever.invoke(query)
            with open("retrieved_docs.txt", "w") as f:
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
        
