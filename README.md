# 📄 AI-Powered PDF Document Q&A (RAG Lite)

A lightweight **Retrieval-Augmented Generation (RAG)** application built with **Python** and **Streamlit** for interactive question answering over PDF documents.

The application processes document embeddings locally using **Hugging Face Sentence Transformers**, retrieves relevant document content using **ChromaDB**, and generates answers through the **Groq API**.

---

## 📌 Project Overview

Reading and searching through lengthy PDF documents manually can be time-consuming. This project provides a simple conversational interface that allows users to upload a PDF document and ask questions about its contents.

The system follows a lightweight RAG pipeline:

```text
PDF Document
     │
     ▼
Document Loading
     │
     ▼
Text Splitting
     │
     ▼
Local Embeddings
     │
     ▼
ChromaDB
     │
     ▼
Relevant Context Retrieval
     │
     ▼
Groq LLM
     │
     ▼
Generated Answer
```

Unlike fully cloud-based RAG systems, the document embedding process is performed locally, while the retrieved context is sent to the Groq API for answer generation.

---

## 🚀 Features

* 📄 **PDF Document Upload**
  Upload PDF documents directly through the Streamlit interface.

* 🧠 **Local Embeddings**
  Uses Hugging Face `sentence-transformers` to generate document embeddings locally.

* 🗄️ **Vector Database**
  Uses ChromaDB to store and retrieve document embeddings efficiently.

* ⚡ **Fast LLM Inference**
  Integrates with the Groq API for fast response generation.

* 🔐 **Secure API Key Input**
  Provides a dedicated API key input and trigger mechanism through the Streamlit sidebar.

* 💬 **Interactive Q&A**
  Ask questions about the uploaded document through a conversational interface.

* 🖥️ **Streamlit Interface**
  Provides a simple and interactive web-based user interface.

---

## 🛠️ Tech Stack

| Technology                             | Purpose                        |
| -------------------------------------- | ------------------------------ |
| **Python**                             | Main programming language      |
| **Streamlit**                          | Web application interface      |
| **LangChain**                          | RAG application framework      |
| **ChromaDB**                           | Vector database                |
| **Hugging Face Sentence Transformers** | Local document embeddings      |
| **Groq API**                           | Large Language Model inference |

---

## 🔄 How It Works

### 1. Upload PDF

The user uploads a PDF document through the Streamlit interface.

### 2. Extract and Split Text

The document content is extracted and divided into smaller chunks to make retrieval more effective.

### 3. Generate Embeddings

Each text chunk is converted into a numerical vector representation using a Hugging Face Sentence Transformer model.

The embedding process runs locally on the user's computer.

### 4. Store in ChromaDB

The generated embeddings are stored in ChromaDB, allowing the system to efficiently search for relevant sections of the document.

### 5. Retrieve Relevant Context

When the user asks a question, the application searches the vector database for document chunks that are semantically relevant to the question.

### 6. Generate an Answer

The retrieved context is provided to the LLM through the Groq API, which generates the final response.

---

# 📁 Project Structure

```text
AI-Powered-PDF-QA/
│
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
│
└── ...
```

> The exact file structure may vary depending on the implementation.

---

# ⚙️ Installation & Setup

## 📋 Prerequisites

Make sure the following software is installed:

* Python 3.x
* Git
* pip

A virtual environment is recommended to keep project dependencies isolated.

---

## 1. Clone the Repository

Replace the repository URL with your actual GitHub repository:

```bash
git clone https://github.com/USERNAME-KAMU/nama-repository.git
cd nama-repository
```

---

## 2. Create a Virtual Environment

### Windows

```bash
python -m venv venv
```

Activate the virtual environment:

```bash
venv\Scripts\activate
```

### macOS / Linux

```bash
python3 -m venv venv
```

Activate the virtual environment:

```bash
source venv/bin/activate
```

---

## 3. Install Dependencies

Install the required Python packages:

```bash
pip install -r requirements.txt
```

---

# 🔑 Groq API Key

This application requires a **Groq API key** for LLM inference.

The API key can be entered through the application's Streamlit sidebar.

> **Important:** Never commit your API key directly into the Git repository.

If you are implementing the API key through environment variables, create a `.env` file locally and make sure it is included in `.gitignore`.

Example:

```text
GROQ_API_KEY=your_api_key_here
```

---

# ▶️ Running the Application

After installing the dependencies and configuring the API key, run the Streamlit application:

```bash
streamlit run app.py
```

The application will provide a local address that can be opened in a web browser.

---

# 💬 Example Usage

1. Launch the Streamlit application.
2. Enter your Groq API key through the sidebar.
3. Upload a PDF document.
4. Wait for the document to be processed.
5. Enter a question related to the uploaded document.
6. The system retrieves relevant information from the document.
7. The LLM generates an answer based on the retrieved context.

### Example Questions

```text
"What is the main objective of this document?"

"Summarize the methodology described in the document."

"What are the main conclusions?"

"What are the key findings discussed in Chapter 3?"
```

---

# 🔐 Security Considerations

The application is designed to avoid hardcoding API credentials in the source code.

However, users should still follow basic API key security practices:

* Never commit API keys to GitHub.
* Never share API keys publicly.
* Add `.env` files to `.gitignore`.
* Regenerate the API key if it is accidentally exposed.
* Use environment variables or secure secret management for deployment.

---

# ⚠️ Limitations

This project is intentionally designed as a lightweight RAG implementation and may have several limitations:

* The quality of answers depends on the quality of the retrieved document chunks.
* Complex PDF layouts, tables, scanned documents, and images may not be processed perfectly.
* LLM responses may contain inaccuracies.
* API usage is dependent on the availability and limits of the Groq service.
* Large documents may require significant local memory for embedding and vector storage.

---

# 🔮 Future Improvements

Potential improvements include:

* [ ] Add support for multiple PDF documents.
* [ ] Add document metadata filtering.
* [ ] Display retrieved document sources alongside answers.
* [ ] Add conversation memory.
* [ ] Improve chunking strategies.
* [ ] Support scanned PDFs using OCR.
* [ ] Add support for tables and images.
* [ ] Add configurable retrieval parameters.
* [ ] Add document preview functionality.
* [ ] Add persistent vector storage.
* [ ] Add deployment configuration for cloud hosting.

---

# 🎯 Project Goal

This project demonstrates the implementation of a lightweight **Retrieval-Augmented Generation (RAG)** pipeline by combining:

**Document Processing → Local Embeddings → Vector Search → Context Retrieval → LLM Generation**

It is intended as a practical demonstration of how Large Language Models can be combined with external document knowledge to build interactive document question-answering applications.

---

# 👨‍💻 Author

**Andika**

Built with Python, LangChain, ChromaDB, Hugging Face, Groq, and Streamlit.
