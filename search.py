import math

def cosine(a, b):
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb)

def search_docs(query_emb, docs):
    scored = []
    for d in docs:
        score = cosine(query_emb, d["embedding"])
        scored.append((score, d))
    scored.sort(reverse=True)
    return [d for _, d in scored[:5]]
