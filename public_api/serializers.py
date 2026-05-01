from rest_framework import serializers

from books.models import Author, Book


class AuthorSerializer(serializers.ModelSerializer):
    """Serializer for Author model."""

    class Meta:
        model = Author
        fields = ["id", "name", "birth_year", "bio"]


class AuthorDetailSerializer(AuthorSerializer):
    """Detailed serializer for Author with books."""

    books = serializers.SerializerMethodField()

    class Meta(AuthorSerializer.Meta):
        fields = AuthorSerializer.Meta.fields + ["books"]

    def get_books(self, obj):
        """Get books for this author (limited to 50)."""
        books = obj.books.prefetch_related("authors", "genres").order_by("title")[:50]
        return BookSerializer(books, many=True, context=self.context).data


class BookSerializer(serializers.ModelSerializer):
    """Basic serializer for Book model."""

    authors = AuthorSerializer(many=True, read_only=True)
    genres = serializers.StringRelatedField(many=True)
    avg_rating = serializers.FloatField(read_only=True)
    rating_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "authors",
            "genres",
            "publication_year",
            "avg_rating",
            "rating_count",
            "cover_image",
        ]


class BookDetailSerializer(BookSerializer):
    """Detailed serializer for Book model."""

    isbn = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    pages = serializers.IntegerField(read_only=True)
    publisher = serializers.StringRelatedField(read_only=True)
    language = serializers.StringRelatedField(read_only=True)

    class Meta(BookSerializer.Meta):
        fields = BookSerializer.Meta.fields + [
            "isbn",
            "description",
            "pages",
            "publisher",
            "language",
        ]
