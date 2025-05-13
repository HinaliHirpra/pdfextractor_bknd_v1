from flask import Flask, request, jsonify
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import io
import base64
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
from pdf2image import convert_from_bytes

# from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

# from flask_cors import CORS

from pymongo import MongoClient,server_api
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
CORS(app)

load_dotenv()  # Load variables from .env
openai.api_key = os.getenv("OPENAI_API_KEY")
uri = os.getenv("MongoDB_URI")
# Create a new client and connect to the server
client = MongoClient(uri, server_api=server_api.ServerApi('1'))

db = client["pdfextractordb"]
products_collection = db["pdfextractor"]

cloudinary.config(
    cloud_name=os.getenv("cloud_name"),
    api_key=os.getenv("cloud_api_key"),
    api_secret=os.getenv("cloud_api_secret")
)

MODEL = "gpt-4o"
MAX_TOKENS_PER_CHUNK = 3000
CHUNK_OVERLAP = 100

@app.route('/api/dataextract', methods=['POST'])

def process():
    try:
        if 'pdf_file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        url=''
        file = request.files['pdf_file']
        file_bytes = file.stream.read()
        images= convert_from_bytes(file_bytes)
        images1 = extract_images_from_pdf(file_bytes)
        for image in images1:
            if is_product_image(image["buffer"]):
                url = upload_to_cloudinary(image)
                # merged_data["url"] = url
                break
                # return jsonify({"product_image_url": url})
        text = extract_text_with_ocr(images)
        chunks = chunk_text(text)
        all_data = [ask_openai(build_prompt(chunk)) for chunk in chunks]
        merged_data = merge_data(all_data)
      
        if url:
            merged_data["url"] = url
        insterdata_flag=products_collection.insert_one(merged_data)
              
        return str(insterdata_flag)
                
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


def extract_text_with_ocr(images):
    # images = convert_from_path(pdf_path)
    # images = convert_from_bytes(pdf_path.read())
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

def extract_images_from_pdf(pdf_bytes):
    # pdf_bytes = file_stream.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            img_bytes = base_image["image"]
            ext = base_image["ext"]
            image = Image.open(io.BytesIO(img_bytes))

            buffer = io.BytesIO()
            image.save(buffer, format=ext.upper())
            buffer.seek(0)

            images.append({
                "name": f"page{page_num+1}_img{img_index+1}.{ext}",
                "buffer": buffer
            })

    return images

# === Function: Use OpenAI to check if image is a product ===
def is_product_image(image_buffer):
    encoded = base64.b64encode(image_buffer.getvalue()).decode("utf-8")
    data_url = f"data:image/png;base64,{encoded}"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "This image is from a pdf. Does it show a physical product (like a machine, device, or equipment)? Respond only with: 'product', 'not product', or 'unclear'."},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            max_tokens=10
        )
        result = response["choices"][0]["message"]["content"].strip().lower()
        return result == "product"
    except Exception as e:
        print("OpenAI Error:", e)
        return False
    
# === Function: Upload image to Cloudinary ===
def upload_to_cloudinary(image_data):
    result = cloudinary.uploader.upload(image_data["buffer"], folder="pdf_product_images/", public_id=image_data["name"])
    return result["secure_url"]

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

# app = Flask(__name__)

# if __name__ == '__main__':
#     app.run(host="0.0.0.0", port=8000)
