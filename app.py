import os

import tempfile

import streamlit as st

from langchain_community.document_loaders import PyPDFLoader

from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_community.embeddings import HuggingFaceEmbeddings

from langchain_chroma import Chroma

from langchain_classic.chains import create_retrieval_chain

from langchain_classic.chains.combine_documents import create_stuff_documents_chain

from langchain_core.prompts import ChatPromptTemplate

from langchain_groq import ChatGroq



# Konfigurasi Halaman Streamlit

st.set_page_config(page_title="RAG Lite - Local & Free", page_icon="🤖", layout="wide")



st.title("📄 AI-Powered PDF Document Q&A (RAG Lite - Free Version)")

st.markdown("Aplikasi RAG menggunakan Hugging Face Embeddings & Groq LLM (100% Gratis!)")



# Sidebar untuk Konfigurasi API Key Groq dengan Tombol Trigger

with st.sidebar:

    st.header("⚙️ Konfigurasi")

   

    # Inisialisasi session state untuk API key jika belum ada

    if "submitted_api_key" not in st.session_state:

        st.session_state.submitted_api_key = ""



    # Input text biasa (tidak langsung memicu aksi sebelum tombol diklik)

    temp_api_key = st.text_input("Masukkan Groq API Key", type="password")

   

    # Tambahkan Tombol Trigger di bawahnya

    if st.button("Simpan API Key", type="primary"):

        if temp_api_key:

            st.session_state.submitted_api_key = temp_api_key

            st.success("API Key berhasil disimpan!")

        else:

            st.error("Kolom API Key masih kosong!")



    st.markdown("---")

    st.markdown("### 📋 Panduan Gratis:")

    st.markdown("1. Buat API Key gratis di [console.groq.com](https://console.groq.com/)")

    st.markdown("2. Masukkan kunci ke kolom di atas.")

    st.markdown("3. Klik tombol **Simpan API Key**.")

    st.markdown("4. Unggah PDF dan tanyakan isinya!")



# Gunakan kunci yang sudah disimpan di session state untuk aplikasi

groq_api_key = st.session_state.submitted_api_key



if not groq_api_key:

    st.warning("⚠️ Silakan masukkan dan simpan Groq API Key Anda di sidebar untuk melanjutkan.")

    st.stop()



# 1. Document Ingestion & Session State

if "vector_store" not in st.session_state:

    st.session_state.vector_store = None

if "chat_history" not in st.session_state:

    st.session_state.chat_history = []



uploaded_file = st.file_uploader("Pilih file PDF", type=["pdf"])



if uploaded_file is not None:

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:

        tmp_file.write(uploaded_file.getvalue())

        tmp_path = tmp_file.name



    with st.spinner("Memproses dokumen secara lokal (Embedding & Chunking)..."):

        try:

            # Load PDF

            loader = PyPDFLoader(tmp_path)

            docs = loader.load()



            # 2. Text Splitting (Chunking)

            text_splitter = RecursiveCharacterTextSplitter(

                chunk_size=500,

                chunk_overlap=50

            )

            chunks = text_splitter.split_documents(docs)



            # 3 & 4. Embedding Generation (Hugging Face - Berjalan Lokal & Gratis)

            embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

            vector_store = Chroma.from_documents(chunks, embeddings)

           

            st.session_state.vector_store = vector_store

            st.success(f"Berhasil memproses {len(chunks)} potongan teks secara lokal!")

       

        except Exception as e:

            st.error(f"Terjadi kesalahan saat memproses PDF: {e}")

        finally:

            if os.path.exists(tmp_path):

                os.remove(tmp_path)



# 5. Retrieval & Generation (Querying / Chat Interface)

if st.session_state.vector_store is not None:

    retriever = st.session_state.vector_store.as_retriever(

        search_type="similarity",

        search_kwargs={"k": 3}

    )

   

    llm = ChatGroq(

        groq_api_key=groq_api_key,

        model_name="openai/gpt-oss-20b",

        temperature=0.2

    )



    system_prompt = (

        "Anda adalah asisten AI yang cerdas dan membantu. "

        "Gunakan konteks berikut yang diambil dari dokumen untuk menjawab pertanyaan. "

        "Jika Anda tidak tahu jawabannya, katakan saja bahwa Anda tidak tahu.\n\n"

        "Konteks:\n{context}"

    )

   

    prompt = ChatPromptTemplate.from_messages([

        ("system", system_prompt),

        ("human", "{input}"),

    ])



    question_answer_chain = create_stuff_documents_chain(llm, prompt)

    rag_chain = create_retrieval_chain(retriever, question_answer_chain)



    # Tampilkan riwayat chat

    for message in st.session_state.chat_history:

        with st.chat_message(message["role"]):

            st.markdown(message["content"])



    # Input Chat dari Pengguna

    if user_query := st.chat_input("Tanyakan sesuatu tentang dokumen PDF..."):

        st.session_state.chat_history.append({"role": "user", "content": user_query})

        with st.chat_message("user"):

            st.markdown(user_query)



        with st.chat_message("assistant"):

            with st.spinner("Berpikir..."):

                response = rag_chain.invoke({"input": user_query})

                answer = response["answer"]

                st.markdown(answer)

                st.session_state.chat_history.append({"role": "assistant", "content": answer})

else:

    st.info("👆 Silakan unggah dokumen PDF di atas untuk mulai melakukan tanya jawab.")