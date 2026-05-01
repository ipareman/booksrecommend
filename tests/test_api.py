import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from books.models import Book, Author, Genre
from public_api.models import ApiKey


@pytest.fixture
def api_client():
    """DRF test client."""
    return APIClient()


@pytest.fixture
def api_key(user):
    """Create an API key for testing."""
    key, raw_key = ApiKey.create_key(owner=user, name="Test Key")
    return raw_key


@pytest.mark.django_db
class TestBookAPI:
    """Tests for Book API endpoints."""

    def test_books_list_requires_auth(self, api_client):
        """Test that books list requires authentication."""
        response = api_client.get("/api/v1/books/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_books_list_with_auth(self, api_client, api_key, book):
        """Test that books list works with valid API key."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get("/api/v1/books/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 1

    def test_books_list_search(self, api_client, api_key, book):
        """Test search functionality in books list."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get("/api/v1/books/?q=Тестовая")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 1

    def test_book_detail(self, api_client, api_key, book):
        """Test book detail endpoint."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get(f"/api/v1/books/{book.pk}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == book.pk
        assert response.data["title"] == book.title

    def test_book_detail_not_found(self, api_client, api_key):
        """Test book detail with non-existent ID."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get("/api/v1/books/99999/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_books_ordering(self, api_client, api_key, author):
        """Test ordering of books."""
        book1 = Book.objects.create(
            title="A Book", publication_year=2020, avg_rating=3.0, rating_count=5
        )
        book2 = Book.objects.create(
            title="B Book", publication_year=2021, avg_rating=5.0, rating_count=10
        )
        book1.authors.add(author)
        book2.authors.add(author)
        
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get("/api/v1/books/?ordering=-avg_rating")
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert results[0]["avg_rating"] >= results[1]["avg_rating"]


@pytest.mark.django_db
class TestAuthorAPI:
    """Tests for Author API endpoints."""

    def test_authors_list_requires_auth(self, api_client):
        """Test that authors list requires authentication."""
        response = api_client.get("/api/v1/authors/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_authors_list_with_auth(self, api_client, api_key, author):
        """Test that authors list works with valid API key."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get("/api/v1/authors/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 1

    def test_authors_list_search(self, api_client, api_key, author):
        """Test search functionality in authors list."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get("/api/v1/authors/?q=Тестовый")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 1

    def test_author_detail(self, api_client, api_key, author):
        """Test author detail endpoint."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get(f"/api/v1/authors/{author.pk}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == author.pk
        assert response.data["name"] == author.name

    def test_author_detail_with_books(self, api_client, api_key, author, book):
        """Test author detail includes books."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get(f"/api/v1/authors/{author.pk}/")
        assert response.status_code == status.HTTP_200_OK
        assert "books" in response.data
        assert len(response.data["books"]) >= 1


@pytest.mark.django_db
class TestAPIKeyAuthentication:
    """Tests for API key authentication."""

    def test_invalid_api_key(self, api_client):
        """Test that invalid API key is rejected."""
        api_client.credentials(HTTP_AUTHORIZATION="Bearer invalid_key")
        response = api_client.get("/api/v1/books/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_api_key_in_header(self, api_client, api_key):
        """Test API key in Authorization header."""
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = api_client.get("/api/v1/books/")
        assert response.status_code == status.HTTP_200_OK

    def test_api_key_in_custom_header(self, api_client, api_key):
        """Test API key in X-API-Key header."""
        api_client.credentials(HTTP_X_API_KEY=api_key)
        response = api_client.get("/api/v1/books/")
        assert response.status_code == status.HTTP_200_OK
