# app/services/azure_blob_service.py
import uuid
from azure.storage.blob import BlobServiceClient
from app.core.config import AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER_NAME

class FileUploader:
    def __init__(self):
        self.blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        self.container_name = AZURE_STORAGE_CONTAINER_NAME

    def upload_file(self, file_content: bytes, file_name: str) -> str:
        unique_filename = f"{uuid.uuid4()}-{file_name}"
        blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=unique_filename)
        
        # Create container if it doesn't exist
        try:
            self.blob_service_client.create_container(self.container_name)
        except Exception:
            pass # Container already exists
        
        blob_client.upload_blob(file_content, overwrite=True)
        return blob_client.url

file_uploader = FileUploader()