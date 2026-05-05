# KrakenCLI dependency bump slices plan

**Goal:** zredukować ryzyko przyszłych alertów Dependabot i problemów kompatybilności bez robienia jednego dużego, trudnego do debugowania bumpa.

**Stan potwierdzony:**
- GitHub Dependabot dla `voytas75/KrakenCLI` pokazuje `0` otwartych alertów.
- `requirements.txt` zawiera kilka starych pinów.
- Clean install na Python 3.13 wywala się już na `pandas==2.1.4`.

## Rekomendowana kolejność PR-ów

### PR 1 — patch/security-low-risk
Cel: małe, bezpieczne podbicia bez ruszania stosu scientific.

Zakres:
- `requests==2.33.0 -> 2.33.1`
- `PyYAML==6.0.1 -> 6.0.3`
- `schedule==1.2.1 -> 1.2.2`
- opcjonalnie `click==8.1.8 -> 8.3.3`

Weryfikacja:
- install w czystym venv na Python 3.12
- wybrane szybkie testy CLI/utils
- smoke: `python kraken_cli.py --help`

Ryzyko: niskie.

### PR 2 — terminal/UI/websocket slice
Cel: ograniczony bump bibliotek interfejsowych i komunikacyjnych.

Zakres:
- `rich==13.7.0 -> 15.0.0`
- `websockets==12.0 -> 16.0`

Weryfikacja:
- testy CLI
- ewentualne miejsca formatowania rich/table
- testy lub smoke ścieżek websocketowych jeśli istnieją

Ryzyko: średnie.

### PR 3 — scientific/runtime compatibility slice
Cel: usunąć główny dług kompatybilności i przygotować repo pod nowsze Pythony.

Zakres kandydacki:
- `pandas==2.1.4 -> 2.3.x albo 3.0.x` (zacząć od najmniejszego sensownego skoku)
- `scipy==1.12.0 -> nowsza kompatybilna linia`
- `scikit-learn==1.5.0 -> nowsza kompatybilna linia`

Weryfikacja:
- pełniejszy test suite
- import/scenariusze w `analysis/`, `indicators/`, `strategies/`
- potwierdzenie instalacji na Python 3.13

Ryzyko: wysokie.

## Potwierdzone obserwacje do użycia w PR-ach

### 1. Piny aktualne / nie wymagają ruchu teraz
- `litellm==1.83.14` — aktualne
- `python-dotenv==1.2.2` — aktualne
- `colorama==0.4.6` — aktualne

### 2. Piny stare, ale raczej do małego bumpa
- `requests==2.33.0`
- `PyYAML==6.0.1`
- `schedule==1.2.1`
- `click==8.1.8`

### 3. Piny stare i potencjalnie bardziej wrażliwe
- `rich==13.7.0`
- `websockets==12.0`
- `pandas==2.1.4`
- `scipy==1.12.0`
- `scikit-learn==1.5.0`

### 4. Twardy fakt kompatybilności
- `pandas==2.1.4` nie instaluje się poprawnie na Python 3.13 w czystym venv.
- To nie jest dziś alert bezpieczeństwa, ale to realny problem utrzymaniowy.

## Operacyjny następny krok
Zacząć od **PR 1** z małym batchem:
- requests
- PyYAML
- schedule
- click

To daje niski koszt, niski blast radius i poprawia higienę zależności przed większym scientific slice.
