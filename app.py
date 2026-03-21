import streamlit as st 
from classifier import classify_message
from responder import generate_response

st.set_page_config(page_title="LLM Triage System") #add page icon 
st.title("LLM Triage & Response System")
st.markdown("Paste an incoming message to classify it, score its priority, and generate a suggested response.")

message = st.text_area("Incoming Message", height = 150, placeholder = "Paste a message here...")

if st.button("Process Message") and message:
    with st.spinner("Analayzing..."):
        classification = classify_message(message)
        response = generate_response(message, classification)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Category", classification["category"].replace("_", " ").title())
    with col2: 
        colors = {"high": "🟢", "medium": "🟡", "low": "🔴"}
        p = classification["priority"]
        st.metric("Priority", f"{colors[p]} {p.title()}")

    st.markdown("**Reasoning**")
    st.info(classification["reasoning"])
    st.markdown("**Suggested Response**")
    st.success(response)
    