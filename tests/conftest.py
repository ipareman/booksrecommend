import pytest
from django.contrib.auth.models import User
from django.test import Client
from books.models import Book, Author, Genre, UserList


@pytest.fixture
def client():
    """Django test client."""
    return Client()


@pytest.fixture
def user(django_db_setup, django_db_blocker):
    """Create a test user."""
    with django_db_blocker.unblock():
        user, created = User.objects.get_or_create(
            username="testuser",
            defaults={
                "email": "test@example.com",
                "password": "testpass123"
            }
        )
        if not created:
            user.set_password("testpass123")
            user.save()
        return user


@pytest.fixture
def staff_user(django_db_setup, django_db_blocker):
    """Create a staff user for admin panel tests."""
    with django_db_blocker.unblock():
        user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.com",
                "password": "adminpass123",
                "is_staff": True
            }
        )
        if not created:
            user.set_password("adminpass123")
            user.is_staff = True
            user.save()
        return user


@pytest.fixture
def author(django_db_setup, django_db_blocker):
    """Create a test author."""
    with django_db_blocker.unblock():
        author, created = Author.objects.get_or_create(
            name="Тестовый Автор",
            defaults={
                "bio": "Тестовая биография",
                "birth_year": 1980
            }
        )
        return author


@pytest.fixture
def genre(django_db_setup, django_db_blocker):
    """Create a test genre."""
    with django_db_blocker.unblock():
        genre, created = Genre.objects.get_or_create(
            name="Фантастика"
        )
        return genre


@pytest.fixture
def book(django_db_setup, django_db_blocker, author, genre):
    """Create a test book."""
    with django_db_blocker.unblock():
        book, created = Book.objects.get_or_create(
            title="Тестовая Книга",
            defaults={
                "isbn": "1234567890",
                "description": "Тестовое описание",
                "publication_year": 2020,
                "pages": 300,
                "avg_rating": 4.5,
                "rating_count": 10
            }
        )
        book.authors.add(author)
        book.genres.add(genre)
        return book


@pytest.fixture
def user_list(django_db_setup, django_db_blocker, user, book):
    """Create a test user list."""
    with django_db_blocker.unblock():
        user_list, created = UserList.objects.get_or_create(
            user=user,
            name="Избранное",
            defaults={
                "is_default": True,
                "sentiment_tag": "positive"
            }
        )
        user_list.books.add(book)
        return user_list
