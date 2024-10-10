from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import List, Dict, Any
import uvicorn
from youtube_transcript_api import YouTubeTranscriptApi
import re
from pymongo import MongoClient
from dotenv import load_dotenv
from bson.objectid import ObjectId
import os

load_dotenv()

app = FastAPI()

class Input(BaseModel):
    input: List[Dict[str, Any]]

class VideoUrl(BaseModel):
    url: HttpUrl

def get_db():
    db_client = MongoClient(os.getenv('MONGO_DB_URI'))
    return db_client[os.getenv('MONGO_DB_NAME')]

def extractive_summarize(text: str, num_sentences: int=None):
    if num_sentences is None:
        words = text.split()
        num_sentences = max(3, min(20, len(words) // 100))  # 1 sentence per 100 words, min 3, max 20
    
    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = LexRankSummarizer()
    summary = summarizer(parser.document, num_sentences)
    return " ".join(str(sentence) for sentence in summary)

def get_result(summary: str, transcription: List[Dict[str, Any]], is_video_id: bool = True):
    offset_key = "start" if is_video_id else "offset"
    print(summary)
    print(len(summary))
    final_summary = [data for data in transcription if any(str(sentence) in summary for sentence in PlaintextParser.from_string(data["text"], Tokenizer("english")).document.sentences)]
    
    results = []
    current_segment = None
    
    for item in final_summary:
        if current_segment and item[offset_key] == current_segment['offset'] + current_segment['duration']:
            current_segment['text'] += ' ' + item['text']
            current_segment['duration'] += item['duration']
        else:
            if current_segment:
                results.append(current_segment)
            current_segment = {
                'text': item['text'],
                'duration': item['duration'],
                'offset': item[offset_key]
            }
    
    if current_segment:
        results.append(current_segment)
    
    return results

def extract_video_id(url: str) -> str:
    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    raise ValueError("Invalid YouTube URL")

def get_transcription(video_id: str) -> List[Dict[str, Any]]:
    try:
        return YouTubeTranscriptApi.get_transcript(video_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Unable to fetch transcript: {str(e)}")

@app.get("/")
def hello():
    return {"result": "Hello, I am working"}

@app.post("/highlight_doc_id")
def get_highlight(doc_id: str):
    db = get_db()
    collection = db["llm_documents"]
    document = collection.find_one({"thread_source": ObjectId(doc_id)})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    collection = db["thread_source_datas"]
    document2 = collection.find_one({"_id": ObjectId(doc_id)})
    if not document2 or "youtube_metadata" not in document2:
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    transcription = document2["youtube_metadata"]["transcriptions"][0]["transcription"]
    text = " ".join(t["text"] for t in transcription)
    summary = extractive_summarize(text)
    return get_result(summary, transcription,False)

@app.post("/highlight_video_id")
def get_highlight2(video: VideoUrl):
    try:
        video_id = extract_video_id(str(video.url))
        transcription = get_transcription(video_id)
        text = " ".join(t["text"] for t in transcription)
        summary = extractive_summarize(text)
        result = get_result(summary, transcription)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

if __name__ == "__main__":
   uvicorn.run(app, host="127.0.0.1", port=8000)
   #get_highlight('66e93041a3c9215abac21587')