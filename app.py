from flask import Flask, request, jsonify
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import openai
import pandas as pd
import json
import re
import tiktoken
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageTk, ImageSequence
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side
from openpyxl.drawing.image import Image as ExcelImage
import fitz
from tkinter import ttk
import threading
import json
from bson import json_util
from flask import Flask
from flask_cors import CORS
import os
from dotenv import load_dotenv

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

# from flask_cors import CORS

from pymongo import MongoClient
# from googletrans import Translator
from deep_translator import GoogleTranslator

# Initialize translator
# translator = Translator()
uri = "mongodb+srv://admin-tool-786:wmqzOaoc5AzeRKiP@cluster0.9jitvus.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
# Create a new client and connect to the server
client = MongoClient(uri, server_api=ServerApi('1'))
# client = MongoClient("mongodb://localhost:27017/")
# print(client.list_database_names())
db = client["pdfextractordb"]
products_collection = db["pdfextractor"]
# print(products_collection)


app = Flask(__name__)
CORS(app)

# === OpenAI Config ===
load_dotenv()  # Load variables from .env
api_key = os.getenv("OPENAI_API_KEY")
# print(api_key)

MODEL = "gpt-4o"
MAX_TOKENS_PER_CHUNK = 3000
CHUNK_OVERLAP = 100
# # Example GET endpoint
# @app.route('/api/hello', methods=['GET'])
# def hello():
#     return jsonify({"message": "Hello, world!"})

# Example POST endpoint
# @app.route('/api/sum', methods=['POST'])
# def sum_numbers():
#     data = request.json
#     result = data.get('a', 0) + data.get('b', 0)
#     return jsonify({"sum": result})

@app.route('/api/dataextract', methods=['POST'])

def process():
    try:
        datapath=request.json
        path=datapath.get('path')
        text = extract_text_with_ocr(path)
        chunks = chunk_text(text)
        all_data = [ask_openai(build_prompt(chunk)) for chunk in chunks]
        merged_data = merge_data(all_data)
        insterdata_flag=products_collection.insert_one(merged_data)
              
        return str(insterdata_flag)
                # insterdata_flag=insertdata(merged_data)
    except Exception as e:
        # return e
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
        # print("Error in process():", e)

# === OCR and GPT Processing Functions ===

@app.route('/api/datagetall', methods=['POST'])

def data_get_all():
    all_data = list(products_collection.find())
    json_data = json.loads(json_util.dumps(all_data))
    return json_data

@app.route('/api/datagetbyname', methods=['POST'])

def data_get_by_name():
    datapath=request.json
    productname=datapath.get('product')
    all_data = list(products_collection.find({"product":productname}))
    json_data = json.loads(json_util.dumps(all_data))
    return json_data

# @app.route('/api/datatranslation', methods=['POST'])
# # Recursive translation function
# def translate_value():
#     data = request.json
#     translated_data = process_translate_value(data)
#     return json.dumps(translated_data)

# def process_translate_value(value):
#     if isinstance(value, str):
#         return GoogleTranslator(source='auto', target='th').translate(value)
#     if isinstance(value, list):
#         return [process_translate_value(item) for item in value]
#     if isinstance(value, dict):
#         return {k: process_translate_value(v) for k, v in value.items()}
#     return value

def extract_text_with_ocr(pdf_path):
    images = convert_from_path(pdf_path)
    full_text = ""
    for i, img in enumerate(images):
        text = pytesseract.image_to_string(img, lang="tha+eng")
        full_text += f"\n--- Page {i+1} ---\n{text}"
    return full_text

def chunk_text(text, max_tokens=3000):
    encoding = tiktoken.encoding_for_model(MODEL)
    tokens = encoding.encode(text)
    chunks = [encoding.decode(tokens[i:i + max_tokens]) for i in range(0, len(tokens), max_tokens - CHUNK_OVERLAP)]
    return chunks

def build_prompt(text):
    return f"""
You are a PDF document data extractor with formatting awareness.

You will receive plain text extracted via OCR from a PDF document. Your tasks are:
1. Identify product number and extract the **product number**.
2. Identify and extract the **product name**.
3. Identify product brand and extract the **brand**.
4. Identify and extract **product features** as bullet points or key-value pairs and Do not include **tables** (structured as list of lists).
5. Identify and extract any **tables** (structured as list of lists).
6. Identify paragraphs or **descriptive text** and Do not include **tables** (structured as list of lists).
7. Capture any **other product-related info** (specs, usage, etc.) and Do not include **tables** (structured as list of lists).

Respond with strict JSON in this format:

{{
  "productnumber": "Product Number",
  "product": "Product Name 1",
  "brand": "Brand",
  "features": ["Feature 1", "Feature 2", ...],
  "tables": [
    [
      ["Data1", "Data2", ...],
      ...
    ],
     [
      ["Data1", "Data2", ...],
      ...
    ],
    ...
  ],
  "descriptions": ["Description 1", "Description 2", ...],
  "others": ["Other info 1", "Other info 2", ...]
}}

Here is the extracted OCR text:

{text}
"""
def ask_openai(prompt):
    response = openai.ChatCompletion.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    content = response['choices'][0]['message']['content']
    content = re.sub(r"^```(json)?|```$", "", content.strip(), flags=re.MULTILINE)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"tables": [], "descriptions": [content.strip()]}
    

def merge_data(chunks_data):
    merged = {"productnumber":None,"product": None,"brand":None, "features": [], "tables": [], "descriptions": [], "others": []}
    for data in chunks_data:
        if not merged["product"] and "product" in data:
            merged["product"] = data["product"]
        if not merged["productnumber"] and "productnumber" in data:
            merged["productnumber"] = data["productnumber"]
        if not merged["brand"] and "brand" in data:
            merged["brand"] = data["brand"]
        
        merged["features"].extend(data.get("features", []))
        merged["tables"].extend(data.get("tables", []))
        merged["descriptions"].extend(data.get("descriptions", []))
        merged["others"].extend(data.get("others", []))
    return merged

def extract_images_from_pdf(pdf_path, output_folder="extracted_images"):
    os.makedirs(output_folder, exist_ok=True)
    doc = fitz.open(pdf_path)
    image_paths = []
    for i in range(len(doc)):
        page = doc[i]
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_path = f"{output_folder}/page{i+1}_img{img_index+1}.{base_image['ext']}"
            with open(image_path, "wb") as f:
                f.write(base_image["image"])
            image_paths.append(image_path)
    return image_paths

@app.route('/api/datatranslation', methods=['POST'])
def translate_data():
    json_data=request.json
    prompt = f"""Translate all values in the following JSON object from English to Thai, but do not change or translate any keys or structural elements. Keep the JSON format exactly the same. Only translate the string values.
            Here is the JSON:
        {json.dumps(json_data, ensure_ascii=False, indent=2)}
        """
    
    response = openai.ChatCompletion.create(
                model="gpt-4o",  # Or gpt-4 / gpt-3.5-turbo
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that translates structured data."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )

    translated_json_text = response['choices'][0]['message']['content']
    translated_json_text = re.sub(r"^```(json)?|```$", "", translated_json_text.strip(), flags=re.MULTILINE)
    return translated_json_text

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000)
