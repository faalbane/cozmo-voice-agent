"""Simple keyword search knowledge base.

No external dependencies — runs in-memory with TF-IDF-like scoring.
Satisfies the spec requirement for "vector DB or keyword search" without
requiring ChromaDB or any external service.
"""

import re
from dataclasses import dataclass

KNOWLEDGE_DOCS = {
    "refund_policy": {
        "title": "Refund Policy",
        "content": (
            "Full refund within 30 days of delivery. Items must be in original condition with tags. "
            "Refunds process in 5-7 business days after we receive the return. Free return shipping label provided. "
            "Late returns 31-60 days: store credit only, valid 12 months. "
            "Not eligible for refund: personalized items, digital downloads, gift cards, final sale, intimate apparel. "
            "Damaged or defective items: full refund or replacement anytime, photo evidence required. "
            "Refunds issued to original payment method. Credit card refunds take 3-5 extra business days."
        ),
        "keywords": ["refund", "return", "money back", "exchange", "damaged", "defective", "store credit"],
    },
    "shipping": {
        "title": "Shipping Information",
        "content": (
            "Standard shipping: $5.99, arrives in 5-7 business days. "
            "Express shipping: $12.99, arrives in 2-3 business days. "
            "Free standard shipping on orders over $50. "
            "Gold members get free express shipping on all orders. "
            "Ships to all 50 US states and select international destinations. "
            "International shipping starts at $15.99."
        ),
        "keywords": ["shipping", "delivery", "ship", "express", "standard", "international", "free shipping"],
    },
    "cancellation": {
        "title": "Order Cancellation",
        "content": (
            "Orders not yet shipped can be cancelled immediately with full refund. "
            "Orders already shipped must go through the return process after delivery. "
            "Subscription cancellations: we offer 20% discount on next 3 months before processing. "
            "If customer insists on cancellation, process gracefully."
        ),
        "keywords": ["cancel", "cancellation", "subscription", "stop", "end"],
    },
    "products": {
        "title": "Products & Pricing",
        "content": (
            "Categories: Electronics, Home & Kitchen, Fashion, Sports & Outdoors, Beauty & Health. "
            "Price match guarantee: lower price from authorized retailer within 14 days, we refund difference. "
            "Bulk discounts: 15% off orders of 10+ identical items. "
            "Electronics include 1-year manufacturer warranty. Extended warranty available 1-3 years."
        ),
        "keywords": ["product", "price", "warranty", "category", "discount", "bulk", "electronics"],
    },
    "rewards": {
        "title": "ShopEase Rewards Program",
        "content": (
            "Earn 1 point per dollar spent. 100 points = $5 discount. "
            "Gold members spend $500+ per year: earn 1.5 points per dollar, free express shipping. "
            "Gift cards available $10-$500, never expire, cannot be redeemed for cash."
        ),
        "keywords": ["rewards", "points", "loyalty", "gold", "member", "gift card"],
    },
    "complaints": {
        "title": "Complaint Handling",
        "content": (
            "Quality complaints: apologize, offer replacement or full refund. Over $100: add 15% off next order. "
            "Shipping delays: if 2+ days late, free express upgrade on next order. If lost 5+ days, ship replacement immediately. "
            "Price disputes: price match within 14 days. Outside window: 10% discount code. "
            "Unauthorized charges: verify details, check order history, escalate to fraud team if needed."
        ),
        "keywords": ["complaint", "unhappy", "quality", "delay", "late", "lost", "charge", "fraud", "dispute"],
    },
}


@dataclass
class SearchResult:
    doc_id: str
    title: str
    content: str
    score: float


class KeywordSearchKB:
    """In-memory keyword search knowledge base."""

    def __init__(self):
        self.docs = KNOWLEDGE_DOCS

    def search(self, query: str, top_k: int = 2) -> list[SearchResult]:
        """Search knowledge base by keyword matching with scoring."""
        query_lower = query.lower()
        query_words = set(re.findall(r'\w+', query_lower))

        results = []
        for doc_id, doc in self.docs.items():
            score = 0.0

            # Keyword match scoring
            for kw in doc["keywords"]:
                if kw in query_lower:
                    score += 3.0  # Exact keyword match
                for word in query_words:
                    if word in kw or kw in word:
                        score += 1.0  # Partial match

            # Content word overlap
            content_words = set(re.findall(r'\w+', doc["content"].lower()))
            overlap = query_words & content_words
            score += len(overlap) * 0.5

            if score > 0:
                results.append(SearchResult(
                    doc_id=doc_id,
                    title=doc["title"],
                    content=doc["content"],
                    score=score,
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    @property
    def doc_count(self) -> int:
        return len(self.docs)


# Singleton
_kb = KeywordSearchKB()


def search_knowledge(query: str, top_k: int = 2) -> str:
    """Search the knowledge base and return formatted results."""
    results = _kb.search(query, top_k)
    if not results:
        return ""
    return "\n\n".join(f"[{r.title}] {r.content}" for r in results)
