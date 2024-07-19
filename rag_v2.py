import os
import yaml
import time
from colorama import Fore, Style
from langchain_community.document_loaders.pdf import PDFPlumberLoader
from langchain_experimental.text_splitter import SemanticChunker
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import Docx2txtLoader, UnstructuredExcelLoader, TextLoader, UnstructuredHTMLLoader, UnstructuredPowerPointLoader, PythonLoader
####  Vector Stores
from langchain_community.vectorstores import FAISS
import chromadb
from langchain_chroma import Chroma
from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter
from langchain_community.tools.tavily_search import TavilySearchResults
####  Models
# Ollama
from langchain_community.llms.ollama import Ollama
# Cohere
from langchain_cohere import CohereEmbeddings, ChatCohere, CohereRagRetriever, create_cohere_react_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor
import cohere
from cohere.errors import BadRequestError
from dotenv import load_dotenv
import json
from copy import copy

load_dotenv()

llm = ChatCohere()
llm = Ollama(model="mistral")

class VectorStore:

    def __init__(self, config, vector_db, vector_collection):
        
        self.vectorstore = self._initialize_component(config[vector_db])
        self.vector_collection = vector_collection
        self.channels = config.get('channels', [])
        self.current_channel = None
        self.retriever = self._initialize_method('as_retriever', 
                                                 config[vector_db]['as_retriever'].get('args', []),
                                                 config[vector_db]['as_retriever'].get('kwargs', {}))

    
    def __str__(self) -> str:
        return f"VectorStore(vectorstore={self.vectorstore})"

    def _initialize_component(self, component_config):
        component_class = globals()[component_config['class']]
        params = component_config.get('params', {})
        return component_class(**params)
    
    def _initialize_method(self, method, args, kwargs):
        if hasattr(self.vectorstore, method):
            return getattr(self.vectorstore, method)(**args, **kwargs)
        else:
            raise AttributeError(f"{self.vectorstore} does not have a method {method}")
    
    def add_document_to_vectorstore(self, doc):
        self.vectorstore.add_documents(doc)
    
    

    



class RAGModel:
    def __init__(self, config, model_family, model_version, vectorstore):
        self.llm = self._initialize_component(config['llm'])
        self.model_family = model_family
        self.model_version = model_version
        self.Vectorstore = vectorstore
        
    
    def __str__(self) -> str:
        return f"RAGModel(llm={self.llm}) - VectorStore(vectorstore={self.vectorstore})"

    def _initialize_component(self, component_config):
        component_class = globals()[component_config['class']]
        params = component_config.get('params', {})
        return component_class(**params)


def my_rag_model_constructor(loader, node):
    return loader.construct_mapping(node, deep=True)
        
yaml.add_constructor('!Class', my_rag_model_constructor, Loader=yaml.FullLoader)

def load_model_from_yaml(yaml_file, model_family, model_version, vector_db) -> tuple:
    with open(yaml_file, 'r') as file:
        config = yaml.load(file, Loader=yaml.FullLoader)
    # Return the model configuration dictionary instead of an instance of MyRAGModel
    model_config = config['LLM_MODELS'][model_family][model_version]
    vector_config = config['VECTORSTORES']
    return model_config, vector_config

def get_model_version(yaml_file, model_family, model_version, vector_db) -> RAGModel:
    model_config, vector_config = load_model_from_yaml(yaml_file, model_family, model_version, vector_db)

    rag_model = RAGModel(config=model_config, model_family=model_family, model_version=model_version, 
                         vectorstore=VectorStore(config=vector_config, vector_db=vector_db, 
                                                 vector_collection='default'))
    
    return rag_model

rag_model = get_model_version("config_v2.yml", 'CohereModels', 'luna-1-cohere', 'Chroma')
print(rag_model.Vectorstore.retriever.invoke("Hello, how are you?"))

