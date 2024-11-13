import streamlit as st
import requests
import base64
from htmltemp import user_template
import time

def typewriter(text, template, speed):
    tokens = text.split()
    container = st.empty()
    for index in range(len(tokens) + 1):
        curr_full_text = " ".join(tokens[:index])
        container.markdown(curr_full_text)
        time.sleep(1 / speed)

# RAG API URL
api_url = "Invoke_URL"

st.title("PDF Chat - RAG Pipeline")
st.write("Upload a PDF and enter a question to get answers based on the PDF content.")

# Allow PDF upload
uploaded_pdf = st.file_uploader("Choose a PDF file", type="pdf")

# Input for the question
question = st.text_input("Question")

if st.button("Get Answer"):
    if uploaded_pdf and question:
        # Read PDF content and encode it as base64
        pdf_base64 = base64.b64encode(uploaded_pdf.read()).decode("utf-8")
        # API request payload
        payload = {
            "pdf_base64": pdf_base64,
            "question": question
        }

        # Send request to RAG pipeline API
        response = requests.post(api_url, json=payload)

        # Display response
        if response.status_code == 200:
            answer = response.json().get("answer", "No answer found.")
            st.write("### Answer:")
            typewriter(answer, user_template, 10)
            st.success("Done!")
        else:
            st.error("Error retrieving answer. Please try again.")
    else:
        st.warning("Please upload a PDF and enter a question.")
