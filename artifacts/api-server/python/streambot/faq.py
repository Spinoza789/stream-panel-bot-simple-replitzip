"""Customer FAQ shown in the bot. Written by the owner in the admin dashboard; empty until they add entries."""
import json

from .service import CheckoutError

KEY = 'faq_items'


class Faq:
    MAX_ITEMS = 30
    MAX_QUESTION = 120
    MAX_ANSWER = 1500

    def __init__(self, service):
        self.service = service; self.store = service.store

    def items(self):
        raw = self.store.metadata(KEY)
        try: data = json.loads(raw) if raw else []
        except ValueError: data = []
        return [dict(question=i['question'], answer=i['answer']) for i in data
                if isinstance(i, dict) and isinstance(i.get('question'), str) and isinstance(i.get('answer'), str)] if isinstance(data, list) else []

    def save(self, actor, items):
        self.service.resellers.finance.admin(actor)
        if not isinstance(items, list) or len(items) > self.MAX_ITEMS:
            raise CheckoutError('Keep the FAQ to %d questions or fewer.' % self.MAX_ITEMS)
        clean = []
        for item in items:
            question = item.get('question') if isinstance(item, dict) else None
            answer = item.get('answer') if isinstance(item, dict) else None
            if not isinstance(question, str) or not isinstance(answer, str):
                raise CheckoutError('Each FAQ entry needs a question and an answer.')
            question, answer = ' '.join(question.split()), answer.strip()
            if not 1 <= len(question) <= self.MAX_QUESTION:
                raise CheckoutError('Questions must be 1 to %d characters.' % self.MAX_QUESTION)
            if not 1 <= len(answer) <= self.MAX_ANSWER:
                raise CheckoutError('Answers must be 1 to %d characters.' % self.MAX_ANSWER)
            clean.append(dict(question=question, answer=answer))
        self.store.metadata(KEY, json.dumps(clean))
        return clean
