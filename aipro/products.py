from dataclasses import dataclass
from typing import Callable

from .fetchers import PriceResult
from .sites import driffle, maads, z2u


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    url: str            # clean product URL (tracking redirects here)
    currency: str       # expected native currency; anything else => "needs review"
    fetch: Callable[[], PriceResult]


PRODUCTS: dict[str, Product] = {p.id: p for p in (
    Product("maads", "MAADS", maads.URL, "EGP", maads.fetch),
    Product("z2u", "Z2U", z2u.URL, "USD", z2u.fetch),
    Product("driffle", "Driffle", driffle.URL, driffle.CURRENCY, driffle.fetch),
)}
