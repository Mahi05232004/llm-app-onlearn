import sys
import os
import json
# import torch
from tqdm import tqdm

# Add parent directory to sys.path
# TODO **: This is a workaround for local imports; consider using a proper package structure
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from utils.embeddings import get_embedding

INPUT_DIR = "../data/dsa_data_updated_strict.json"
OUTPUT_DIR = "../data/dsa_data_with_embedding.json"

with open(INPUT_DIR, 'r') as file:
    questions = json.load(file)

# Loop through questions
for question in tqdm(questions, desc="Embedding Questions"):
    concepts_query = ''.join(
    concept
    for k in ['sub_concepts', 'concepts', 'standard_concepts']
    for concept in question.get(k, [])
)

    query = (
        question.get('question_topic', '') +
        question.get('question_title', '') +
        question.get('sub_step_title', '') +
        question.get('step_title', '') +
        concepts_query
    )

    embedding_tensor = get_embedding(query)
    question['embedding'] = embedding_tensor.tolist()

# Save
with open(OUTPUT_DIR, 'w') as file:
    json.dump(questions, file, indent=2)