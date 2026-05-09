import pytest
from django.test import Client
from django.contrib.auth.models import User
from django.urls import reverse
from books.models import Book, Author, Genre


@pytest.mark.django_db
class TestHomeView:
    """Tests for home page view."""

    def test_home_page_loads(self, client):
        """Test that home page loads successfully."""
        response = client.get("/")
        assert response.status_code == 200

    def test_home_page_context(self, client, book):
        """Test that home page has correct context."""
        response = client.get("/")
        assert response.status_code == 200
        assert "popular" in response.context
        assert "newest" in response.context


@pytest.mark.django_db
class TestCommunityView:
    """Tests for community page view."""

    def test_community_page_loads(self, client):
        """Test that community page loads successfully."""
        response = client.get("/community/")
        assert response.status_code == 200

    def test_community_page_authenticated(self, client, user):
        """Test community page with authenticated user."""
        client.force_login(user)
        response = client.get("/community/")
        assert response.status_code == 200
        assert "community_stats" in response.context


@pytest.mark.django_db
class TestLuckyView:
    """Tests for lucky/random book view."""

    def test_lucky_page_loads(self, client):
        """Test that lucky page loads successfully."""
        response = client.get("/lucky/")
        assert response.status_code == 200

    def test_lucky_spin_with_books(self, client, book):
        """Test that lucky spin returns a book when books exist."""
        response = client.get("/lucky/spin/")
        assert response.status_code == 200
        data = response.json()
        if data.get("ok"):
            assert "id" in data
            assert "title" in data


@pytest.mark.django_db
class TestDesignDemos:
    """Tests for design demo pages."""

    def test_design_demos_page_loads(self, client):
        """Test that design demos page loads."""
        response = client.get("/design-demos/")
        assert response.status_code == 200

    def test_typewriter_home_demo_loads(self, client):
        """Test that typewriter home demo loads."""
        response = client.get("/typewriter-home-demo/")
        assert response.status_code == 200

    def test_typewriter_community_demo_loads(self, client):
        """Test that typewriter community demo loads."""
        response = client.get("/typewriter-community-demo/")
        assert response.status_code == 200

    def test_subscription_demo_loads(self, client):
        """Test that subscription demo page loads."""
        response = client.get("/subscription/")
        assert response.status_code == 200

    def test_subscription_yookassa_demo_redirects(self, client, settings, monkeypatch):
        """Test that YooKassa action redirects to hosted payment page."""
        class YooKassaResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"confirmation": {"confirmation_url": "https://yoomoney.ru/demo-payment"}}

        settings.YOOKASSA_SHOP_ID = ""
        settings.YOOKASSA_SECRET_KEY = ""
        response = client.post("/subscription/yookassa/")
        assert response.status_code == 302
        assert response["Location"] == "/subscription/"

        settings.YOOKASSA_SHOP_ID = "test-shop"
        settings.YOOKASSA_SECRET_KEY = "test-secret"

        import core.views
        monkeypatch.setattr(core.views.requests, "post", lambda *args, **kwargs: YooKassaResponse())
        response = client.post("/subscription/yookassa/")

        assert response.status_code == 302
        assert response["Location"] == "https://yoomoney.ru/demo-payment"


@pytest.mark.django_db
class TestErrorPages:
    """Tests for custom error pages."""

    def test_404_page(self, client):
        """Test custom 404 page."""
        response = client.get("/nonexistent-page/")
        assert response.status_code == 404

    def test_500_page(self, client):
        """Test custom 500 page (requires triggering error)."""
        # 500 page is tested through Django's test client
        # Actual 500 error would need to be triggered
        pass
