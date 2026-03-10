# import torch
# import torch.nn.functional as F
# from transformers import AutoTokenizer, AutoModel

# # Load model and tokenizer once
# tokenizer = AutoTokenizer.from_pretrained('Qwen/Qwen3-Embedding-0.6B', padding_side='left')
# model = AutoModel.from_pretrained('Qwen/Qwen3-Embedding-0.6B')
# model.eval()  # set to inference mode

# # Optional: move model to GPU if available
# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# model.to(device)


# def last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
#     """Pool the last valid token embedding from the hidden states."""
#     left_padding = (attention_mask[:, -1].sum() == attention_mask.shape[0])
#     if left_padding:
#         return last_hidden_states[:, -1]
#     else:
#         sequence_lengths = attention_mask.sum(dim=1) - 1
#         batch_size = last_hidden_states.shape[0]
#         return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]


# def get_embedding(text: str) -> torch.Tensor:
#     """Return the normalized embedding vector for a given input text."""
#     inputs = tokenizer(
#         text,
#         return_tensors="pt",
#         truncation=True,
#         padding=True,
#         max_length=8192
#     ).to(device)

#     normalized = None

#     with torch.no_grad():
#         outputs = model(**inputs)
#         pooled = last_token_pool(outputs.last_hidden_state, inputs['attention_mask'])
#         normalized = F.normalize(pooled, p=2, dim=1)

#     return normalized if normalized[0] else None  # Return a 1D tensor of shape (embedding_dim,)

def get_embedding(text: str):
    pass