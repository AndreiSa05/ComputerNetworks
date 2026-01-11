# Security Policy RAG

A **Retrieval-Augmented Generation (RAG)** application designed to ingest security policy documents (PDFs) and provide accurate, context-aware answers to user queries using AI.

This project utilizes an event-driven architecture to handle document processing asynchronously, ensuring a responsive user interface even when processing large files.

---

## Architecture & Tech Stack

* **FastAPI**: Backend API framework
* **Streamlit**: Frontend User Interface
* **Inngest**: Event orchestration and background job management
* **Qdrant**: Vector database for semantic search
* **OpenAI**: Text Embeddings (`text-embedding-3-large`) and LLM
* **LlamaIndex**: PDF parsing and text chunking
* **Python 3.12+**: Core programming language

### Repository Structure

| File | Description |
| :--- | :--- |
| `app.py` | **Frontend**: The Streamlit dashboard. Handles user input, file uploads, and displays answers. |
| `main.py` | **Backend**: The FastAPI server containing Inngest functions for ingesting PDFs and processing queries. |
| `vector_db.py` | **Database Layer**: Manages interactions with Qdrant (upserting vectors, searching context). |
| `data_loader.py` | **Data Processing**: Utilities to read PDFs, split text into chunks, and generate embeddings. |
| `custom_types.py` | **Schemas**: Pydantic models used for type safety across the application. |

---

### Prerequisites

- Python 3.12 or higher
- OpenAI API key
- Inngest account
- Qdrant instance (local or cloud)

### Environment Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/AndreiSa05/ComputerNetworks.git
   cd ComputerNetworks
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -e .
   ```
4. Start the Qdrant vector database:
   ```bash
   docker run -d -p 6333:6333 -v ./qdrant_storage:/qdrant/storage
   ```
5. Create a .env file with your configuration and add your api key here:
   ```bash
   touch .env
   ```
   ```
   OPENAI_API_KEY=your_openai_api_key
   ```
   
### Running the Application
The backend, Inngest server, and frontend must run simultaneously in separate terminals.

1. Terminal 1: Backend (FastAPI) 
   Starts the API server that processes the logic.
   ```bash
   uvicorn main:app --reload
   ```
2. Terminal 2: Inngest Dev Server
   Starts the local event dashboard and connects it to your FastAPI backend.
   ```bash
   npx inngest-cli@latest dev -u http://127.0.0.1:8000/api/inngest --no-discovery
   ``` 
3. Terminal 3: Frontend (Streamlit)
   Starts the user interface.
   ```bash
   streamlit run app.py   # On Windows: streamlit run .\app.py
   ```
### Usage
1. Access the App:
   - Open http://localhost:8501 in your browser.

2. Inngest Dashboard: 
   - Open http://localhost:8288 to visualize events and background jobs.

3. Upload a PDF:
   - Use the upload widget to add a Security Policy PDF.
   - Check the Inngest Dashboard to see the rag/ingest_pdf event processing.

4. Ask Questions:
   - Select the uploaded policy from the sidebar/list.
   - Type a question like: "What is the password complexity requirement?"
   - Click Ask.

5. View Results: The AI will return the answer, and the specific source documents used.
