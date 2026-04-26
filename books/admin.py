from django.contrib import admin
from .models import Book, Author, Genre, Publisher, Series, Language, UserList, Store, BookStore


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display  = ["title", "get_authors", "publication_year", "avg_rating", "avg_price"]
    list_filter   = ["genres", "publication_year"]
    search_fields = ["title", "isbn", "authors__name"]
    filter_horizontal = ["authors", "genres"]
    readonly_fields   = ["avg_rating", "rating_count", "avg_price", "price_last_requested"]

    def get_authors(self, obj):
        return ", ".join(a.name for a in obj.authors.all())
    get_authors.short_description = "Авторы"


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display  = ["name", "base_url", "price_selector", "is_active"]
    list_editable = ["is_active"]
    search_fields = ["name"]


@admin.register(BookStore)
class BookStoreAdmin(admin.ModelAdmin):
    list_display  = ["book", "store", "current_price", "in_stock", "last_checked"]
    list_filter   = ["store", "in_stock"]
    search_fields = ["book__title"]
    readonly_fields = ["last_checked"]


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display  = ["name", "birth_year"]
    search_fields = ["name"]


admin.site.register(Genre)
admin.site.register(Publisher)
admin.site.register(Series)
admin.site.register(Language)
admin.site.register(UserList)
