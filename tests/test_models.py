import pytest
from books.models import Book, Author, Genre, UserList


@pytest.mark.django_db
class TestAuthor:
    """Tests for Author model."""

    def test_author_creation(self, author):
        """Test that author can be created."""
        assert author.name == "Тестовый Автор"
        assert author.birth_year == 1980
        assert str(author) == "Тестовый Автор"

    def test_author_ordering(self):
        """Test that authors are ordered by name."""
        Author.objects.create(name="Б автор", birth_year=1990)
        Author.objects.create(name="А автор", birth_year=1985)
        authors = list(Author.objects.all())
        assert authors[0].name == "А автор"
        assert authors[1].name == "Б автор"


@pytest.mark.django_db
class TestGenre:
    """Tests for Genre model."""

    def test_genre_creation(self, genre):
        """Test that genre can be created."""
        assert genre.name == "Фантастика"
        assert str(genre) == "Фантастика"

    def test_genre_unique(self):
        """Test that genre name is unique."""
        from django.db import IntegrityError
        Genre.objects.create(name="Фантастика")
        with pytest.raises(IntegrityError):
            Genre.objects.create(name="Фантастика")


@pytest.mark.django_db
class TestBook:
    """Tests for Book model."""

    def test_book_creation(self, book, author, genre):
        """Test that book can be created."""
        assert book.title == "Тестовая Книга"
        assert book.isbn == "1234567890"
        assert book.publication_year == 2020
        assert book.pages == 300
        assert book.avg_rating == 4.5
        assert author in book.authors.all()
        assert genre in book.genres.all()

    def test_book_stars_display(self, book):
        """Test stars_display property."""
        book.avg_rating = 4.0
        book.save()
        assert book.stars_display == "★★★★☆"

    def test_book_ordering(self, author):
        """Test that books are ordered by avg_rating."""
        book1 = Book.objects.create(
            title="Книга 1", publication_year=2020, avg_rating=3.0, rating_count=5
        )
        book2 = Book.objects.create(
            title="Книга 2", publication_year=2021, avg_rating=5.0, rating_count=10
        )
        book1.authors.add(author)
        book2.authors.add(author)
        books = list(Book.objects.all())
        assert books[0].avg_rating >= books[1].avg_rating


@pytest.mark.django_db
class TestUserList:
    """Tests for UserList model."""

    def test_user_list_creation(self, user_list, user, book):
        """Test that user list can be created."""
        assert user_list.name == "Избранное"
        assert user_list.user == user
        assert user_list.is_default is True
        assert user_list.sentiment_tag == "positive"
        assert book in user_list.books.all()

    def test_user_list_unique_constraint(self, user):
        """Test that user+name combination is unique."""
        from django.db import IntegrityError
        UserList.objects.create(user=user, name="Тест")
        with pytest.raises(IntegrityError):
            UserList.objects.create(user=user, name="Тест")

    def test_user_list_sentiment_choices(self, user_list):
        """Test that sentiment tag has valid choices."""
        valid_choices = ["positive", "negative", "neutral", "wishlist"]
        assert user_list.sentiment_tag in valid_choices
