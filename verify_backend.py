
import requests
import os

BASE_URL = "http://127.0.0.1:8000"

def test_file_upload_and_qa():
    # 1. Create a dummy test file
    with open("test_doc.txt", "w") as f:
        f.write("Project Insight is a secretive initiative to categorize cyber threats. The highest priority threat is 'Zero-Day Exploit' which is critical.")
    
    # 2. Upload the file
    print("Testing File Upload...")
    files = {'file': ('test_doc.txt', open('test_doc.txt', 'rb'), 'text/plain')}
    try:
        response = requests.post(f"{BASE_URL}/api/upload_file", files=files)
        print(f"Upload Status: {response.status_code}")
        print(f"Upload Response: {response.json()}")
        
        if response.status_code != 200:
            print("❌ Upload failed.")
            return
    except Exception as e:
        print(f"❌ Upload request failed: {e}")
        return

    # 3. Ask a question about the file
    print("\nTesting File Q&A...")
    query = {
        "prompt": "What is the highest priority threat?",
        "notebook_cells": [],
        "variables": []
    }
    
    try:
        qa_response = requests.post(f"{BASE_URL}/query", json=query)
        print(f"Q&A Status: {qa_response.status_code}")
        data = qa_response.json()
        print(f"Tool Used: {data.get('tool_used')}")
        print(f"Answer:\n{data.get('answer')}")
        
        if data.get('tool_used') == 'FILE_QA':
            print("✅ Intent correctly identified as FILE_QA.")
        else:
            print(f"❌ Intent mismatch. Expected FILE_QA, got {data.get('tool_used')}")
            
    except Exception as e:
        print(f"❌ Q&A request failed: {e}")

    # Cleanup
    if os.path.exists("test_doc.txt"):
        os.remove("test_doc.txt")

if __name__ == "__main__":
    test_file_upload_and_qa()
