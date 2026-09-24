"""Zajedničko za sve testove.

Alat bez identiteta operatera odbija da skenira. Testovi skeniraju lokalni server
(a `pytest -m live` i prave sajtove), pa im treba identitet; testovi koji proveravaju
baš to odbijanje brišu ga preko `monkeypatch.delenv`.
"""

import os

os.environ.setdefault("SKENER_NAZIV", "skener testovi")
os.environ.setdefault("SKENER_KONTAKT", "miloslazic458@gmail.com")
