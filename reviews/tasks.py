import logging
from celery import shared_task
from reviews.models import Review
from books.tag_extraction import extract_tag_from_review, apply_tag_to_book

logger = logging.getLogger(__name__)


@shared_task
def extract_tag_for_review(review_id: int) -> None:
    """
    Celery-задача: вызывает Claude для извлечения тега из одобренного отзыва
    и применяет результат к книге.
    """


    try:
        review = Review.objects.select_related("book").prefetch_related("book__authors").get(pk=review_id)
    except Review.DoesNotExist:
        logger.warning("extract_tag_for_review: review #%d not found", review_id)
        return

    tag = extract_tag_from_review(review)
    if not tag:
        return

    apply_tag_to_book(review.book, tag)

    # Сохраняем тег в отзыве для возможного декремента при отклонении
    review.extracted_tag = tag
    review.save(update_fields=["extracted_tag"])
    logger.info("Tag '%s' applied to book #%d from review #%d", tag, review.book.pk, review_id)


@shared_task
def extract_tag_for_critique(critique_id: int) -> None:
    """
    Celery-задача: извлечение тега из одобренной рецензии (strip HTML → Claude).
    """
    import re
    from reviews.models import Critique

    try:
        critique = (
            Critique.objects
            .select_related("book")
            .prefetch_related("book__authors")
            .get(pk=critique_id)
        )
    except Critique.DoesNotExist:
        logger.warning("extract_tag_for_critique: critique #%d not found", critique_id)
        return

    # Стрипаем HTML для передачи в Claude
    plain_text = re.sub(r"<[^>]+>", "", critique.body)

    # Создаём объект-прокси, совместимый с extract_tag_from_review
    class _Proxy:
        def __init__(self):
            self.text = plain_text
            self.rating = critique.final_rating
            self.book = critique.book
            self.pk = critique.pk

    tag = extract_tag_from_review(_Proxy())
    if not tag:
        return

    apply_tag_to_book(critique.book, tag)
    critique.extracted_tag = tag
    critique.save(update_fields=["extracted_tag"])
    logger.info("Tag '%s' applied to book #%d from critique #%d", tag, critique.book.pk, critique_id)
