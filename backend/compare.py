import PyPDF2
import mesop as me
import google.generativeai as genai
from typing import List
import os
from io import BytesIO
from dotenv import load_dotenv
import pickle
import numpy as np
import pandas as pd
import json

# Load your predictive model
def load_predictive_model():
    filename = './predictive_model/pred_model.sav'
    model = pickle.load(open(filename, 'rb'))
    return model

predictive_model = load_predictive_model()

# Load API key from environment variables
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_GENAI_API_KEY"))

# Initialize the generative model
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash-002",
    generation_config=generation_config,
)

@me.stateclass
class State:
  file: me.UploadedFile

def load(e: me.LoadEvent):
  me.set_theme_mode("system")

@me.page(
  on_load=load,
  security_policy=me.SecurityPolicy(
    allowed_iframe_parents=["https://google.github.io"]
  ),
  path="/",
)
def app():
  state = me.state(State)
  
  with me.box(style=me.Style(padding=me.Padding.all(15))):
    # PDF Uploader
    me.uploader(
      label="Upload PDF File",
      accepted_file_types=["application/pdf"],
      on_upload=handle_upload,
      type="flat",
      color="primary",
      style=me.Style(font_weight="bold"),
    )

    # If file is uploaded, show file details and process it
    if state.file.size:
      with me.box(style=me.Style(margin=me.Margin.all(10))):
        me.text(f"File name: {state.file.name}")
        me.text(f"File size: {state.file.size}")
        me.text(f"File type: {state.file.mime_type}")

      # Process PDF and display results
      analysis_results = process_pdf_and_analyze(state.file)
      for i, result in enumerate(analysis_results):
        me.text(f"Chunk {i+1}: {result}")

def handle_upload(event: me.UploadEvent):
  state = me.state(State)
  state.file = event.file

# Update process_pdf_and_analyze to use Weaviate for chunk storage and retrieval
def process_pdf_and_analyze(file: me.UploadedFile) -> List[str]:
    # Step 1: Extract text from the uploaded PDF file
    pdf_text = extract_text_from_pdf(file)
    
    # Step 2: Chunk the text into smaller pieces
    chunks = chunk_text(pdf_text)
    
    # Step 3: Store chunks in Weaviate
    store_chunks_in_weaviate(weaviate_client, chunks)
    
    # Step 4: Retrieve chunks from Weaviate
    stored_chunks = get_chunks_from_weaviate(weaviate_client)
    
    # Step 5: Analyze each chunk using the preset prompt and combine with predictive model score
    results = []
    for chunk in stored_chunks:
        # Step 5.1: Get the AI model's score
        ai_score = analyze_chunk_with_gemini(chunk)

        # Step 5.2: Get the predictive model's score
        predictive_score = get_predictive_model_score(chunk)

        # Step 5.3: Combine the scores
        final_score = combine_scores(float(ai_score), predictive_score)
        
        results.append(f"{chunk} Combined Truthfulness Score: ({float(ai_score):.2f} + {predictive_score:.2f}) / 2 = {final_score:.2f}")
    
    return results

# Extract text from the uploaded PDF file
def extract_text_from_pdf(file: me.UploadedFile) -> str:
    pdf_stream = BytesIO(file.getvalue())
    reader = PyPDF2.PdfReader(pdf_stream)
    
    extracted_text = ""
    for page in reader.pages:
        extracted_text += page.extract_text()
    
    return extracted_text

# # Chunk text into smaller parts
# def chunk_text(text: str, chunk_size=2000) -> List[str]:
#   words = text.split()
#   chunks = []
#   current_chunk = []
#   current_chunk_length = 0

#   for word in words:
#     current_chunk.append(word)
#     current_chunk_length += len(word) + 1

#     if current_chunk_length > chunk_size:
#       chunks.append(" ".join(current_chunk))
#       current_chunk = []
#       current_chunk_length = 0

#   if current_chunk:
#     chunks.append(" ".join(current_chunk))

#   return chunks

def chunk_text(text: str, chunk_size=2000) -> List[str]:
    from nltk.tokenize import sent_tokenize

    sentences = sent_tokenize(text)
    chunks = []
    current_chunk = []
    current_chunk_length = 0

    for sentence in sentences:
        sentence_length = len(sentence)

        # Check if adding the sentence would exceed chunk size
        if current_chunk_length + sentence_length > chunk_size:
            # Add the current chunk to the list of chunks
            chunks.append(" ".join(current_chunk))
            # Reset current chunk and length
            current_chunk = []
            current_chunk_length = 0

        # Add the sentence to the current chunk
        current_chunk.append(sentence)
        current_chunk_length += sentence_length + 1  # Account for space

    # Add any remaining sentences as the last chunk
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks

## Testing for Weaviate Database
import weaviate
from weaviate.classes.config import Property, DataType
import weaviate.classes.config as wvc

wcd_url = os.getenv("WEAVIATE_CLUSTER")
wcd_api_key = os.getenv("WEAVIATE_API_KEY")
openai_api_key = os.getenv("OPENAI_APIKEY")

# Initialize Weaviate Client
weaviate_client = weaviate.connect_to_weaviate_cloud(
    cluster_url=wcd_url,
    auth_credentials=weaviate.classes.init.Auth.api_key(wcd_api_key),
    headers = {
        "X-OpenAI-Api-Key": openai_api_key,
    }
)

# Define the collection schema for ArticleChunk
def create_article_chunk_schema(client):
    # Create the ArticleChunk collection with text vectorization and generative configuration
    client.collections.create(
        name="ArticleChunk",
        # vectorizer_config=wvc.Configure.Vectorizer.text2vec_openai(),
        # generative_config=wvc.Configure.Generative.openai(),
        properties=[
            Property(name="text", data_type=DataType.TEXT),
        ]
    )

# Define the collection schema for LiarPlusClaim
def create_liar_plus_schema(client):
    client.collections.create(
        name="LiarPlus",
        vectorizer_config=wvc.Configure.Vectorizer.text2vec_openai(),
        generative_config=wvc.Configure.Generative.openai(),
        properties=[
            Property(name="claim", data_type=DataType.TEXT),
            Property(name="label", data_type=DataType.TEXT),
            Property(name="topics", data_type=DataType.TEXT),
            Property(name="originator", data_type=DataType.TEXT),
            Property(name="title", data_type=DataType.TEXT),
            Property(name="party", data_type=DataType.TEXT),
            Property(name="justification", data_type=DataType.TEXT),
        ],
    )

# Delete old schema and create new schema
weaviate_client.collections.delete("ArticleChunk")
# weaviate_client.collections.delete("LiarPlus")
create_article_chunk_schema(weaviate_client)
# create_liar_plus_schema(weaviate_client)

from weaviate.util import generate_uuid5

# Store chunked text in Weaviate using the dynamic batch context
def store_chunks_in_weaviate(client, chunks: List[str]):
    collection = client.collections.get("ArticleChunk")
    
    with collection.batch.dynamic() as batch:
        for chunk in chunks:
            # Generate a unique UUID for each chunk
            obj_uuid = generate_uuid5({"text": chunk})
            batch.add_object(
                properties={"text": chunk},
                uuid=obj_uuid
            )

# Store liar plus in Weaviate using the dynamic batch context
def store_liar_plus_in_weaviate(client, filepath):
    collection = client.collections.get("LiarPlus")
    
    with collection.batch.dynamic() as batch:
        with open(filepath, 'r') as f:
            for line in f:
                claim_data = json.loads(line.strip())

                batch.add_object(
                    properties={
                        "claim": claim_data["claim"],
                        "label": claim_data["label"],
                        "topics": claim_data["topics"],
                        "originator": claim_data["originator"],
                        "title": claim_data["title"],
                        "party": claim_data["party"],
                        "justification": claim_data["justification"]                        
                    },
                    uuid=generate_uuid5(claim_data["id"])
                )
                failed_objs_a = collection.batch.failed_objects  # Get failed objects
                if failed_objs_a:
                    print(f"Number of failed objects in the first batch: {len(failed_objs_a)}")
                    for i, failed_obj in enumerate(failed_objs_a, 1):
                        print(f"Failed object {i}:")
                        print(f"Error message: {failed_obj.message}")
                else:
                    print("All objects were successfully added.")

# store_liar_plus_in_weaviate(weaviate_client, "./data/train2_jsonl.jsonl")

def retrieve_and_analyze_claim(chunk_text):
    response = weaviate_client.query.get("LiarPlus", ["claim", "label", "justification", "topics", "originator", "title", "party"]) \
        .with_near_text({"concepts": [chunk_text]}) \
        .with_limit(3) \
        .do()
    
    # Process the results
    results = []
    for result in response["data"]["Get"]["LiarPlus"]:
        claim_text = result["claim"]
        label = result["label"]
        justification = result["justification"]
        confidence = 1 if label == "true" else 0  # Simplified confidence based on label
        
        results.append({
            "claim": claim_text,
            "label": label,
            "confidence": confidence,
            "justification": justification
        })
    
    return results

# Example Usage
# chunk_text = "Sample text from a chunk in PDF"
# similar_claims = retrieve_and_analyze_claim(chunk_text)
# print(similar_claims)

# Retrieve chunked text from Weaviate
def get_chunks_from_weaviate(client) -> List[str]:
    # Get the collection for querying
    article_chunk_collection = client.collections.get("ArticleChunk")
    
    # Fetch objects with a specified limit and return only the "text" property
    response = article_chunk_collection.query.fetch_objects(
        limit=100,  # Set limit as needed
        return_properties=["text"]
    )
    
    # Extract the "text" property from each returned object
    chunks = [obj.properties["text"] for obj in response.objects if "text" in obj.properties]
    return chunks
## End of testing

# Analyze chunk using Google Gemini AI
def analyze_chunk_with_gemini(chunk: str) -> str:

    new_chat_session = model.start_chat(history=[])
#   preset_prompt = (
#     """
#     Analyze the provided text using the following **Factuality Factors**. Each factor has three mini-factors, and each factor should be scored from 0 to 1 (2 decimal places). After the analysis, generate an overall **Final Truthfulness Score** from 0 to 1, where 0 represents 0% truth and 1 represents 100% truth. A brief explanation for each factor is required. Format your response as follows:

#     ### **1. Biases Factuality Factor**:
#     - **Language Analysis Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of how language bias (overt or covert) is detected or absent.
    
#     - **Tonal Analysis Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of how the tone affects the neutrality or bias of the text.

#     - **Balanced Perspective Checks Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of whether multiple perspectives are fairly represented.

#     ### **2. Context Veracity Factor**:
#     - **Consistency Checks Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of whether the content remains consistent or has contradictions.

#     - **Contextual Shift Detection Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of any shifts in context that could alter the meaning of the text.

#     - **Setting-based Validation Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of whether the claims are valid based on the setting or situation they are presented in.

#     ### **3. Information Utility Factor**:
#     - **Content Value Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of whether the content provides fresh, unbiased information.

#     - **Cost Analysis Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of whether there are additional costs or barriers to accessing reliable information.

#     - **Reader Value Score**: Provide a score between 0 and 1.
#     - Explanation: Brief explanation of how useful the content is to the intended audience.

#     ### **Final Truthfulness Score**:
#     - Based on the above factor scores, calculate the **Final Truthfulness Score** between 0 and 1 (2 decimal places) that represents the overall truthfulness of the text chunk.
#     """
#   )
    preset_prompt = (
        """
        1. Objective:
        - Analyze the provided text using three Objective Functions: Language Analysis, Tonal Analysis, and Balanced Perspective Checks.
        - In each iteration, review your previous output, identify gaps or improvements, and refine your analysis further to achieve greater depth and accuracy.

        2. Instructions for Each Iteration:
        - Iteration 1:
            - Language Analysis: Identify overt and covert language biases. Provide examples where word choices may carry inherent biases that affect interpretation.
            - Tonal Analysis: Assess the tone for any skew in sentiment, noting any bias towards particular topics or groups.
            - Balanced Perspective Checks: Evaluate if multiple perspectives are represented, especially if vital perspectives are missing or underrepresented.
            - Conclude with a preliminary truthfulness score from 0 to 1, with an explanation based on the findings for each objective function.
        - Iteration 2:
            - Task: Reflect on areas where the initial analysis may have missed nuances or misjudged biases. For instance:
                - If certain biases were undetected, explain why they may have been overlooked and analyze with more detail.
                - Re-examine tonal shifts for additional layers or subtleties.
                - Identify specific perspectives that were overlooked in the initial check.
            - Action: Refine the explanations and adjust scores for each objective function. Document adjustments and improvements made.
        - Iteration 3:
            - Objective: Conduct a final review with a focus on maximizing comprehensiveness in perspective diversity and minimizing omitted information or biases.
            - Re-assess each objective function, improving upon gaps or omissions detected in earlier iterations.
            - Summary: Assign final scores to each objective function, explain each, and combine these into an overall Final Truthfulness Score between 0 and 1.
        3. Final Truthfulness Score:
        - Based on refined scores from each iteration, calculate a final truthfulness score that reflects the overall factuality and balance of the text.
        - Include a brief summary, highlighting how each objective function impacted the score and any final observations on the article’s objectivity and completeness.
        4. Please also shows the six breakdown scores, each score is a percentage of the total truthfulness score and add together equals to 1, of the truthfulness score as fellowing format:
        [barely-true, false, half-true, mostly-true, pants-fire, true]
        """
    )
    full_prompt = f"{preset_prompt}\n\nText:\n{chunk}"

    try:
        response = new_chat_session.send_message(full_prompt)
        output = getattr(response._result, "candidates", None)
        if output and len(output) > 0:
            response_text = output[0].content.parts[0].text
            print(output)
            ai_score = extract_ai_score(response_text)  # Extract score from AI response
            return ai_score
        else:
            return "0"  # If no response, default score to 0
    except Exception as e:
        return f"Error processing chunk: {str(e)}"
  
import re

# Extract AI score from the response text
def extract_ai_score(response_text: str) -> float:
    # print(response_text)
    # Use a regular expression to find the final truthfulness score in the format of a floating-point number
    match = re.findall(r"\**Final Truthfulness Score\:\** ([0-9]\.[0-9]+)", response_text)
    
    if match:
        return float(match[0])  # Extract the score as a float
    else:
        return 0.0  # Return 0.0 if no score is found

# Combine the AI and predictive model scores
def combine_scores(ai_score: float, predictive_score: float, weight_ai=0.5, weight_predictive=0.5) -> float:
    return (ai_score * weight_ai) + (predictive_score * weight_predictive)

# Predictive model score function
def get_predictive_model_score(chunk_text: str) -> float:
    # Assuming `combine_feat` is a feature engineering function as in your example
    X_chunk = pd.DataFrame({'Statement': [chunk_text], 'Speaker_Job_Title': ['Unknown'], 'Extracted_Justification': ['None']})
    X_chunk = combine_feat(X_chunk)  # Apply feature engineering to get model input
    y_pred = predictive_model.predict_proba(X_chunk)
    
    # Calculate the weighted score
    weights = [0.4, 0.2, 0.6, 0.8, 0, 1]  # Example weights for each class
    print(y_pred)
    weighted_data = y_pred * weights
    predictive_score = np.sum(weighted_data, axis=1)[0]
    
    return predictive_score

import pandas as pd
import numpy as np
import pickle

from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import nltk
from nltk.corpus import stopwords
from textblob import TextBlob
import spacy
from collections import Counter
import re
import time
import requests
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Load a pre-trained NLP model
# nltk.download('punkt', quiet=True)  # Tokenizer
# nltk.download('stopwords', quiet=True)
stop_words = set(stopwords.words('english'))
# nltk.download('averaged_perceptron_tagger')  # POS tagger
# nltk.download('wordnet')  # WordNet for lemmatization
nlp = spacy.load("en_core_web_sm")

# FF: content statistic

def structural_analysis(statement):
    doc = nlp(statement)
    num_sentences = len(list(doc.sents))
    total_tokens = len([token.text for token in doc])
    
    # Syntactic complexity
    avg_sentence_length = total_tokens / num_sentences if num_sentences > 0 else 0
    tree_depth = max([token.head.i - token.i for token in doc]) if len(doc) > 0 else 0
    
    # Sentiment Analysis
    sentiment = TextBlob(statement).sentiment
    polarity = sentiment.polarity
    subjectivity = sentiment.subjectivity

    return [avg_sentence_length, tree_depth, polarity, subjectivity]

def extract_graph_features(statement):
    doc = nlp(statement)
    pos_counts = Counter([token.pos_ for token in doc])
    entities = Counter([ent.label_ for ent in doc.ents])
    
    # part of speech tagging
    pos_noun = pos_counts.get("NOUN", 0)
    pos_verb = pos_counts.get("VERB", 0)
    pos_adjective = pos_counts.get("ADJ", 0)
    
    # named entity recognition
    num_persons = entities.get("PERSON", 0)
    num_orgs = entities.get("ORG", 0)
    num_gpes = entities.get("GPE", 0)
    
    return [pos_noun, pos_verb, pos_adjective, num_persons, num_orgs, num_gpes]

def extract_comparison_features(statement):
    # Keywords for different LIWC-like categories (simplified)
    cognitive_words = ["think", "know", "understand", "believe"]
    emotional_words = ["happy", "sad", "angry", "fear"]
    social_words = ["friend", "family", "society"]

    # Tokenize statement and count keywords
    vectorizer = CountVectorizer(vocabulary=cognitive_words + emotional_words + social_words)
    word_counts = vectorizer.fit_transform([statement]).toarray().flatten()

    # Divide word counts into different categories
    num_cognitive = sum(word_counts[:len(cognitive_words)])
    num_emotional = sum(word_counts[len(cognitive_words):len(cognitive_words) + len(emotional_words)])
    num_social = sum(word_counts[-len(social_words):])

    return [num_cognitive, num_emotional, num_social]

def extract_feature(statement):
    return np.array(structural_analysis(statement) + extract_graph_features(statement) + extract_comparison_features(statement))

# Function to scrape one page of fact-checks
def scrape_fact_checks(page_number):
    url = f"https://www.politifact.com/factchecks/?page={page_number}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # List to store the fact-check data
    data = []

    # Find all fact-check articles on the page
    fact_checks = soup.find_all('article', class_='m-statement')

    for fact in fact_checks:
        # Extract Author/Speaker
        author = fact.find('a', class_='m-statement__name').text.strip()

        # Extract the Date of the statement
        date_string = fact.find('div', class_='m-statement__desc').text.strip()

        # Use a regular expression to extract only the date portion (e.g., October 8, 2024)
        date_match = re.search(r'([A-Za-z]+ \d{1,2}, \d{4})', date_string)
        date = date_match.group(0) if date_match else "No date found"

        # Extract the Claim (statement being fact-checked)
        claim = fact.find('div', class_='m-statement__quote').find('a').text.strip()

        # Extract the URL to the full fact-check article
        link = "https://www.politifact.com" + fact.find('div', class_='m-statement__quote').find('a')['href']

        # Extract the Rating (e.g., False, Pants on Fire)
        rating = fact.find('div', class_='m-statement__meter').find('img')['alt'].strip()

        # Append the extracted information to the list
        data.append({
            'Author/Speaker': author,
            'Date': date,
            'Claim': claim,
            'Rating': rating,
            'Link to Full Article': link
        })

    return data

# Loop through multiple pages and collect data
def scrape_multiple_pages(start_page, end_page):
    all_data = []
    for page_number in range(start_page, end_page + 1):
        print(f"Scraping page {page_number}...")
        page_data = scrape_fact_checks(page_number)
        all_data.extend(page_data)
        time.sleep(2)  # Sleep for 2 seconds between each page request

    return all_data

# Scrape data from page 1 to 2
data = scrape_multiple_pages(1, 2)
politifact_data = pd.DataFrame(data)
test_link = politifact_data['Link to Full Article'].iloc[0]

test_response = requests.get(test_link)
soup = BeautifulSoup(test_response.text, 'html.parser')

# FF: authenticity

def cross_referenced(x, politifact_data):
    # Get the 'statement' column from the Liar Plus dataset and 'Claim' from PolitiFact
    liar_statements = x['Statement']
    politifact_claims = politifact_data['Claim']

    # Use TF-IDF Vectorizer to convert text to numerical features
    vectorizer = TfidfVectorizer(stop_words='english')

    # Combine both statements and claims for vectorization
    combined_text = pd.concat([liar_statements, politifact_claims], axis=0)

    # Fit and transform the combined text using TF-IDF
    tfidf_matrix = vectorizer.fit_transform(combined_text)

    # Split the transformed matrix into two parts: one for Liar Plus, one for PolitiFact
    liar_tfidf = tfidf_matrix[:len(liar_statements)]
    politifact_tfidf = tfidf_matrix[len(liar_statements):]

    # Compute cosine similarity between every statement in Liar Plus and every claim in PolitiFact
    similarity_matrix = cosine_similarity(liar_tfidf, politifact_tfidf)

    # Find the highest similarity score for each Liar Plus statement
    max_similarity = similarity_matrix.max(axis=1)

    # Set a threshold for similarity (e.g., 0.8) to define a "cross-referenced" statement
    threshold = 0.8
    return (max_similarity >= threshold).astype(int)

# Define a credibility score based on job title (you can customize this based on your data)
def assign_credibility_score(job_title):
    if "scientist" in job_title.lower() or "doctor" in job_title.lower():
        return 3  # High credibility
    elif "senator" in job_title.lower() or "president" in job_title.lower():
        return 2  # Medium credibility
    else:
        return 1  # Low credibility
    
# Function to detect if justification contains references to studies or data
def contains_cited_data(justification):
    keywords = ['according to', 'research', 'study', 'data', 'shown by', 'reported']
    for keyword in keywords:
        if keyword in justification.lower():
            return 1  # Cited data present
    return 0  # No cited data

sid = SentimentIntensityAnalyzer()

# Vectorizer
vectorizer = CountVectorizer(stop_words='english', max_features=50)

def fit_vectorizer(X):
    """Fit the vectorizer on the 'Statement' column of X."""
    vectorizer.fit(X['Statement'])

def transform_data(X):
    """Transform the data and generate the feature set."""
    features = []
    
    # Token/word count for normalization
    X['chunk_length'] = X['Statement'].apply(lambda x: len(x.split()))

    # Writing style and linguistic features
    X['exclamation_count'] = X['Statement'].apply(lambda x: x.count('!')) / X['chunk_length']
    X['question_mark_count'] = X['Statement'].apply(lambda x: x.count('?')) / X['chunk_length']
    X['all_caps_count'] = X['Statement'].apply(lambda x: len(re.findall(r'\b[A-Z]{2,}\b', x))) / X['chunk_length']
    
    # Named Entity Count: Counts the number of named entities in the statement using spaCy
    X['entity_count'] = X['Statement'].apply(lambda x: len(nlp(x).ents)) / X['chunk_length']
    
    # Superlative and adjective count using spaCy
    X['superlative_count'] = X['Statement'].apply(lambda x: len(re.findall(r'\b(best|worst|most|least)\b', x.lower()))) / X['chunk_length']
    X['adjective_count'] = X['Statement'].apply(lambda x: len([token for token in nlp(x) if token.pos_ == 'ADJ'])) / X['chunk_length']

    # Emotion-based word count
    emotion_words = set(['disaster', 'amazing', 'horrible', 'incredible', 'shocking', 'unbelievable'])
    X['emotion_word_count'] = X['Statement'].apply(lambda x: len([word for word in x.lower().split() if word in emotion_words])) / X['chunk_length']

    # Modal verb count
    modal_verbs = set(['might', 'could', 'must', 'should', 'would', 'may'])
    X['modal_verb_count'] = X['Statement'].apply(lambda x: len([word for word in x.lower().split() if word in modal_verbs])) / X['chunk_length']

    # Complex word ratio
    X['complex_word_ratio'] = X['Statement'].apply(lambda x: len([word for word in x.split() if len(re.findall(r'[aeiouy]+', word)) > 2]) / (len(x.split()) + 1))

    # Sentiment analysis using VADER
    X['sentiment_polarity'] = X['Statement'].apply(lambda x: sid.polarity_scores(x)['compound'])
    X['sentiment_subjectivity'] = X['Statement'].apply(lambda x: sid.polarity_scores(x)['neu'])  # Using VADER's neutrality score

    # Flesch Reading Ease
    X['flesch_reading_ease'] = X['Statement'].apply(flesch_reading_ease)

    # Combine all features into a dataframe
    numerical_features = X[['exclamation_count', 'question_mark_count', 'all_caps_count',
                            'entity_count', 'superlative_count', 'adjective_count',
                            'emotion_word_count', 'modal_verb_count', 
                            'complex_word_ratio', 
                            'sentiment_polarity', 'sentiment_subjectivity', 'flesch_reading_ease']]
    
    features.append(numerical_features)
    return pd.concat(features, axis=1)

def flesch_reading_ease(text):
    """Compute Flesch Reading Ease score for readability analysis."""
    sentence_count = max(len(re.split(r'[.!?]+', text)), 1)
    word_count = len(text.split())
    syllable_count = sum([syllable_count_func(word) for word in text.split()])
    if word_count > 0:
        return (206.835 - 1.015 * (word_count / sentence_count) - 84.6 * (syllable_count / word_count)) / 100
    else:
        return 0

def syllable_count_func(word):
    """Count syllables in a word using regular expressions."""
    word = word.lower()
    syllables = re.findall(r'[aeiouy]+', word)
    return max(len(syllables), 1)

# Combine all the engineered features
def combine_feat(X):
    X['cross_referenced'] = cross_referenced(X, politifact_data)  # Cross-referencing feature
    X['credibility_score'] = X['Speaker_Job_Title'].apply(assign_credibility_score)  # Author credentials feature
    X['cited_data'] = X['Extracted_Justification'].apply(contains_cited_data)  # Cited data verification feature
    X_auth = X[['cross_referenced', 'credibility_score', 'cited_data']].to_numpy()
    X_content = np.vstack(X['Statement'].apply(lambda x: extract_feature(x)).to_numpy())
    fit_vectorizer(X)
    X_ling_tox = transform_data(X).to_numpy()
    X = np.hstack((X_content, X_auth, X_ling_tox))
    return X