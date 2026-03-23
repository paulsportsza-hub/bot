# Hollywoodbets Internal API Endpoints Documentation

## Overview

Hollywoodbets uses an ASP.NET Web API backend (with Swagger/Swashbuckle documentation at the Mozambique domain). The frontend is an Angular application that communicates with multiple API subdomains. All domains are protected by Cloudflare, which blocks requests without valid browser cookies/challenges.

**Discovery Method:** Wayback Machine CDX API + JavaScript bundle reverse engineering from the legacy Angular frontend.

---

## Base URLs

| Service | Base URL | Purpose |
|---------|----------|---------|
| **Main Betting API** | `https://betapi.hollywoodbets.net` | Core sports, events, tournaments, betting |
| **Datafree Betting API** | `https://betapi-datafree.hollywoodbets.net` | Zero-rated / data-free variant |
| **Mozambique Betting API** | `https://betapi.hollywoodbets.co.mz` | Mozambique region (has Swagger UI) |
| **Statement API** | `https://betapistatementapi.hollywoodbets.net` | Bet statements and transaction history |
| **Live Games Statement** | `https://api.hollywoodbets.net/statement` | Live games statement data |
| **Identity Service** | `https://id.hollywoodbets.net` | Authentication, password reset |
| **Legacy Token Issuer** | `https://legacy-token-issuer.hollywoodbets.net/api` | Legacy auth token issuance |
| **Explore API** | `https://bet-services-explore-api.hollywoodbets.net/api` | Explore/discovery service |
| **Terminus API** | `https://bet-services-terminus-api.hollywoodbets.net/api` | Self-exclusion, responsible gambling |
| **Content CMS API** | `https://content-cms-api.hollywoodbets.net/api/v1/` | Strapi CMS content |
| **Store API** | `https://store-api.hollywoodbets.net/` | Store/shop data |
| **Region API** | `https://region-api.hollywoodbets.net` | Region detection |
| **Payment API** | `https://allconnect-payment.hollywoodbets.net` | Payment processing |
| **SignalR Hub** | `https://signalrweb.hollywoodbets.net/balancehub` | Real-time balance updates via SignalR |
| **Live In-Play** | `https://inplay.hollywoodbets.net/` | SyX live in-play betting |
| **Gaming Content** | `https://gamingcontent-api.hollywoodbets.net` | Casino/gaming content |
| **Gold Circle Tote** | `https://goldcircletote-api.hollywoodbets.net` | Horse racing tote betting |
| **Sportcast Widget** | `https://sportcast-widget.hollywoodbets.net` | Same-match bet builder widget |
| **Client API** | `https://client-api.hollywoodbets.net` | Client/punter management |
| **Integration Security** | `https://integration-security-api.hollywoodbets.net` | Security/encryption |
| **SIS Streaming** | `https://bet-sisstreaming-api.hollywoodbets.net` | SIS live streaming |
| **Swagger UI (Mozambique)** | `https://betapi.hollywoodbets.co.mz/swagger/ui/index` | API documentation (Swagger spec at `/swagger/docs/v1`) |

---

## FOOTBALL/SOCCER ODDS ENDPOINTS (Primary Interest)

All endpoints below are relative to the **Main Betting API** base URL: `https://betapi.hollywoodbets.net`

### 1. GET /api/sports

**Purpose:** List all available sports.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/sports?lang=en`
- **Query Parameters:**
  - `lang` (string): Language code, e.g., `en`, `pt`
  - `eventStatusIDs` (int, optional): Filter by event status (6 = final/resulted)
  - `startDate` (string, optional): ISO date, e.g., `2024-03-10`
  - `endDate` (string, optional): ISO date, e.g., `2024-03-17`
- **Required Headers:**
  - `Accept: application/json` (Angular frontend uses JSON; archived responses show XML as default)
  - `User-Agent: <browser user-agent>`
  - Cloudflare challenge cookie required for live access
- **Response Format (XML from archive, JSON when `Accept: application/json`):**

```xml
<BaseResponseOfListOfSportModel>
  <ResponseObject>
    <SportModel>
      <Id>1</Id>
      <Name>Soccer</Name>
      <ShortName>Soc</ShortName>
      <SportTypeId>1</SportTypeId>
      <SportIcon>Soccer</SportIcon>
    </SportModel>
    <!-- more sports... -->
  </ResponseObject>
  <ResponseMessage>Success</ResponseMessage>
  <ResponseType>Success</ResponseType>
</BaseResponseOfListOfSportModel>
```

**JSON equivalent:**
```json
{
  "responseObject": [
    {
      "id": 1,
      "name": "Soccer",
      "shortName": "Soc",
      "sportTypeId": 1,
      "sportIcon": "Soccer"
    }
  ],
  "responseMessage": "Success",
  "responseType": "Success"
}
```

**Key Sport IDs:**
| ID | Sport |
|----|-------|
| 1 | Soccer |
| 2 | Basketball |
| 3 | Tennis |
| 4 | Baseball |
| 5 | Ice Hockey |
| 6 | Volleyball |
| 7 | Rugby |
| 8 | Horse Racing |
| 9 | Motorsport |
| 10 | Snooker |
| 12 | Aussie Rules |
| 13 | Golf |
| 18 | Handball |
| 19 | Floorball |
| 21 | Lucky Numbers |
| 60 | Cycling |
| 61 | Darts |
| 62 | American Football |
| 81 | In-Running |
| 84 | Cricket |
| 91 | MMA |
| 93 | Bandy |
| 95 | Futsal |
| 98 | Boxing |
| 100 | Table Tennis |
| 115 | Netball |
| 166 | eSoccer |

---

### 2. GET /api/sports/{sportId}/countries

**Purpose:** List all countries (leagues/regions) for a given sport.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/sports/1/countries`
- **Path Parameters:**
  - `{sportId}` (int): Sport ID (1 for Soccer)
- **Query Parameters:**
  - `allStatuses` (bool, optional): Include all event statuses
  - `outRightsOnly` (bool, optional): Return only outright markets
  - `lang` (string, optional): Language code
  - `endDate` (string, optional): End date filter
- **Response Format:**

```xml
<BaseResponseOfListOfCountryModel>
  <ResponseObject>
    <CountryModel>
      <Id>248</Id>
      <Name>England</Name>
      <IsoCode>EN</IsoCode>
    </CountryModel>
    <CountryModel>
      <Id>2</Id>
      <Name>South Africa</Name>
      <IsoCode>ZA</IsoCode>
    </CountryModel>
    <!-- ~80+ countries for soccer -->
  </ResponseObject>
  <ResponseMessage>Success</ResponseMessage>
  <ResponseType>Success</ResponseType>
</BaseResponseOfListOfCountryModel>
```

**Key Soccer Country IDs:**
| ID | Country/League |
|----|---------------|
| 2 | South Africa |
| 248 | England |
| 65 | Germany |
| 83 | Italy |
| 61 | France |
| 161 | Spain |
| 617 | UEFA Champions League |
| 618 | UEFA Europa League |
| 757 | UEFA Conference League |
| 721 | World Cup 2026 |
| 342 | International Clubs |
| 1 | International |
| 664 | Simulated Reality League |
| 337 | International Youth |

---

### 3. GET /api/sports/{sportId}/countriesandtournaments

**Purpose:** Get countries AND their tournaments with next event info for a sport. This is the primary endpoint for browsing available leagues.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/sports/1/countriesandtournaments?startDate=2024-03-10`
- **Path Parameters:**
  - `{sportId}` (int): Sport ID (1 for Soccer)
- **Query Parameters:**
  - `startDate` (string): ISO date to filter from
- **Response Format:**

```xml
<BaseResponseOfListOfCountriesAndTournaments>
  <ResponseObject>
    <CountriesAndTournaments>
      <Country>
        <Id>248</Id>
        <Name>England</Name>
        <IsoCode>EN</IsoCode>
      </Country>
      <Tournaments>
        <TournamentModel>
          <Id>3092452</Id>
          <Name>Premier League</Name>
          <Date xsi:nil="true" />
          <SportId xsi:nil="true" />
          <CountryId>248</CountryId>
          <NextEvent>
            <Id>5217785</Id>
            <Name>AFC BOURNEMOUTH vs BRIGHTON &amp; HOVE ALBION</Name>
            <DateTime>2023-04-04T11:00:00</DateTime>
          </NextEvent>
          <OutrightsCount xsi:nil="true" />
          <IsOutrights xsi:nil="true" />
        </TournamentModel>
      </Tournaments>
    </CountriesAndTournaments>
  </ResponseObject>
  <ResponseMessage>Success</ResponseMessage>
  <ResponseType>Success</ResponseType>
</BaseResponseOfListOfCountriesAndTournaments>
```

---

### 4. GET /api/events

**Purpose:** Get events (matches) for a tournament. THIS IS THE KEY ENDPOINT FOR FOOTBALL ODDS.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events?tournamentId={tournamentId}&includeExtraInfo={bool}&includeAllStatuses={bool}&startDate={date}&endDate={date}&sportId={sportId}`
- **Query Parameters:**
  - `tournamentId` (int): Tournament ID (e.g., 3092452 for Premier League)
  - `includeExtraInfo` (bool): Include extra event information
  - `includeAllStatuses` (bool): Include all event statuses
  - `startDate` (string): Start date filter
  - `endDate` (string): End date filter
  - `sportId` (int): Sport ID filter
- **Required Headers:** Same as other endpoints
- **Returns:** List of events with their odds/markets

---

### 5. GET /api/events/{eventId}

**Purpose:** Get a specific event's details.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events/{eventId}`
- **Path Parameters:**
  - `{eventId}` (int): Event ID

---

### 6. GET /api/events/{eventId}/markets

**Purpose:** Get all betting markets (odds) for a specific event. THIS IS THE ODDS DETAIL ENDPOINT.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events/{eventId}/markets?byPassEventMarketCache={bool}`
- **Path Parameters:**
  - `{eventId}` (int): Event ID
- **Query Parameters:**
  - `byPassEventMarketCache` (bool, optional): Bypass caching to get fresh odds

---

### 7. GET /api/events/{eventId}/results

**Purpose:** Get results for a finished event.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events/{eventId}/results?lang=en`
- **Path Parameters:**
  - `{eventId}` (int): Event ID
- **Query Parameters:**
  - `lang` (string): Language code

---

### 8. GET /api/events/search

**Purpose:** Search for events by text.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events/search?searchFilter={query}`
- **Query Parameters:**
  - `searchFilter` (string): Search text

---

### 9. GET /api/sports/{sportId}/todayscoupon

**Purpose:** Get today's betting coupon (popular matches) for a sport.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/sports/1/todayscoupon?betTypeId={betTypeId}&lang=en`
- **Path Parameters:**
  - `{sportId}` (int): Sport ID (1 for Soccer)
- **Query Parameters:**
  - `betTypeId` (int): Bet type ID (e.g., 15 for Full Time 1X2)
  - `lang` (string): Language code

---

### 10. GET /api/sports/{sportId}/todayspopularcoupon

**Purpose:** Get today's popular coupon.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/sports/1/todayspopularcoupon?betTypeId={betTypeId}&lang=en`
- **Parameters:** Same as todayscoupon

---

### 11. GET /api/sports/nextsport

**Purpose:** Get next upcoming sport events.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/sports/nextsport?pageSize={size}&pageNum={num}&isLocal={bool}`
- **Query Parameters:**
  - `pageSize` (int): Number of results per page
  - `pageNum` (int): Page number
  - `isLocal` (bool): Filter for local events only

---

## TOURNAMENT ENDPOINTS

### 12. GET /api/tournaments/{tournamentId}

**Purpose:** Get tournament details.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/tournaments/{tournamentId}`

---

### 13. GET /api/tournaments/{tournamentId}/bettypes/{betTypeId}/markets

**Purpose:** Get markets for a specific bet type in a tournament. Important for getting odds by market type.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/tournaments/{tournamentId}/bettypes/{betTypeId}/markets?lang=en`
- **Path Parameters:**
  - `{tournamentId}` (int): Tournament ID
  - `{betTypeId}` (int): Bet type ID
- **Query Parameters:**
  - `lang` (string): Language code

---

### 14. GET /api/tournaments/getcashouttournaments

**Purpose:** Get tournaments that support cash-out.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/tournaments/getcashouttournaments`

---

## BETTING ENDPOINTS

### 15. GET /api/betting/bettypes

**Purpose:** Get all available bet types (market types).

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/betting/bettypes?lang=en`
- **Query Parameters:**
  - `lang` (string): Language code
- **Response:** Returns 60+ bet type models

**Key Soccer Bet Type IDs:**
| ID | Name | Description |
|----|------|-------------|
| 15 | Full Time | 1X2 match result |
| 16 | Half Time | Half-time result |
| 17 | Handicap | Asian/European handicap |
| 18 | First 10 mins | First 10 minutes result |
| 19 | Double Chance | Double chance |
| 20 | Correct Score | Correct score |
| 21 | First Team to Score | First goalscorer (team) |
| 22 | Both Teams to Score | BTTS |
| 23 | Half Time/Full Time | HT/FT |
| 24 | Odd Even Goals | Odd/Even total goals |
| 25 | Goals Home | Home team goals |
| 26 | Goals Away | Away team goals |
| 27 | Totals | Over/Under goals |
| 34 | Clean Sheet | Clean sheet |
| 35 | Half Time Double Chance | HT double chance |
| 36 | First Half Goals | First half total goals |
| 38 | Half Time Handicap | HT handicap |
| 39 | Half With Most Goals | Which half most goals |
| 40 | Early Goal | Early goal |
| 42 | Late Goal | Late goal |
| 43 | Second Half Goals | Second half total goals |
| 47 | Which Team To Score | Which team scores |
| 53 | Handicap 2 | Alternative handicap |
| 60 | Additional Totals | Additional totals |
| 61 | 1st Half Totals | First half O/U |
| 62 | 2nd Half Totals | Second half O/U |
| 63 | Last Team To Score | Last team to score |

---

### 16. GET /api/betting/subbettypes

**Purpose:** Get sub-bet types.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/betting/subbettypes`

---

### 17. GET /api/betting/autostretch

**Purpose:** Get auto-stretch percentages for multi-bets.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/betting/autostretch`
- **Response:**

```xml
<BaseResponseOfListOfAutoStretchModel>
  <ResponseObject>
    <AutoStretchModel>
      <SportID>1</SportID>
      <NumberOfLegs>2</NumberOfLegs>
      <StretchPercentage>2.5</StretchPercentage>
    </AutoStretchModel>
    <!-- more entries for different leg counts -->
  </ResponseObject>
</BaseResponseOfListOfAutoStretchModel>
```

---

### 18. POST /api/betting/submitprovisionalbet

**Purpose:** Submit a provisional bet.

- **HTTP Method:** POST
- **URL:** `https://betapi.hollywoodbets.net/api/betting/submitprovisionalbet`
- **Body:** Bet details (JSON)

---

## LIVE IN-PLAY ENDPOINTS

### 19. GET /api/liveinplay/sports

**Purpose:** Get sports available for live in-play betting.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/liveinplay/sports`
- **Response:** List of live sports

```xml
<BaseResponseOfListOfSportModel>
  <ResponseObject>
    <SportModel><Sport>Football</Sport></SportModel>
    <SportModel><Sport>Tennis</Sport></SportModel>
    <SportModel><Sport>Basketball</Sport></SportModel>
    <SportModel><Sport>Cricket</Sport></SportModel>
    <!-- more sports -->
  </ResponseObject>
</BaseResponseOfListOfSportModel>
```

---

### 20. GET /api/liveinplay/sportfixtures/{sportName}/tournamentsevents

**Purpose:** Get live tournament events for a sport.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/liveinplay/sportfixtures/{sportName}/tournamentsevents`
- **Path Parameters:**
  - `{sportName}` (string): Sport name (e.g., "Football")

---

### 21. GET /api/liveinplay/sportfixtures/{sportName}/upcoming

**Purpose:** Get upcoming live in-play fixtures for a sport.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/liveinplay/sportfixtures/{sportName}/upcoming`

---

### 22. GET /api/liveinplay/{sportName}/bettypecategories

**Purpose:** Get bet type categories available for live in-play for a sport.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/liveinplay/{sportName}/bettypecategories`

---

## OTHER USEFUL ENDPOINTS

### 23. GET /api/sports/sportexotics

**Purpose:** Get sport exotic bet types.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/sports/sportexotics?tournamentId={id}&sportexotics=true`

---

### 24. GET /api/lists/{listId}

**Purpose:** Get static list data.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/lists/{listId}`
- Known list IDs: 13, 18

---

### 25. GET /api/punters/loadAbet

**Purpose:** Load a shared bet by bet code.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/punters/loadAbet/?ShareBetCode={code}`

---

### 26. GET /api/events/getcashoutbettypes

**Purpose:** Get bet types eligible for cash-out.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events/getcashoutbettypes`

---

### 27. GET /api/events/horseracing/nextraces

**Purpose:** Get next horse races.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events/horseracing/nextraces?isLocal={bool}&raceCount={int}`

---

### 28. GET /api/events/{eventId}/exoticdetail

**Purpose:** Get exotic bet details for an event.

- **HTTP Method:** GET
- **URL:** `https://betapi.hollywoodbets.net/api/events/exoticdetail?eventBetTypeGroupId={id}`

---

## CMS ENDPOINTS (Content Management)

### 29. GET /api/cms/{platform}/documents/...

- `GET /api/cms/web/seo-fragments` - SEO fragments
- `GET /api/cms/web/current-active-promotions?punterId=null` - Active promotions
- `GET /api/cms/web/documents/depth/2?noContent=true` - Document tree
- `GET /api/cms/web/documents/hyperlink-key/{id}` - Document by hyperlink key
- `GET /api/cms/web/documents/page-region/{region}` - Documents by page region
- `GET /api/cms/web/documents/path/{path}` - Document by path
- `GET /api/cms/documents/{id}` - Document by ID
- `GET /api/cms/documents/{id}/children` - Child documents
- `GET /api/cms/{platform}?withPromotions=false&withDocuments=true&level=1&punterId=0` - CMS data

Platform values: `web`, `mob`, `mob_pt` (Mozambique Portuguese)

---

## AUTHENTICATION

The API uses OAuth2 with token-based authentication:

- **Token endpoint:** `https://id.hollywoodbets.net/connect/token` (inferred from OAuthModuleConfig)
- **Legacy token issuer:** `https://legacy-token-issuer.hollywoodbets.net/api/issue`
- The `Authorization` header carries `Bearer {token}` for authenticated endpoints
- Authenticated resources (sports/events/tournaments API included): The `accessToken` is sent for `betapi.hollywoodbets.net`, `id.hollywoodbets.net`, `api.hollywoodbets.net/statement`, and `bet-services-explore-api.hollywoodbets.net/api`

**Public endpoints (no auth required):**
- `/api/sports?lang=en`
- `/api/sports/{sportId}/countries`
- `/api/sports/{sportId}/countriesandtournaments`
- `/api/betting/bettypes?lang=en`
- `/api/betting/autostretch`
- `/api/lists/{id}`
- `/api/liveinplay/sports`
- `/api/events?tournamentId=...` (public events listing)

---

## RESPONSE WRAPPER FORMAT

All API responses follow this ASP.NET wrapper pattern:

**JSON:**
```json
{
  "responseObject": [ ... ],
  "responseMessage": "Success",
  "responseType": "Success"
}
```

**XML (default if no Accept header):**
```xml
<BaseResponseOfListOf{ModelName}>
  <ResponseObject>
    <!-- Array of model objects -->
  </ResponseObject>
  <ResponseMessage>Success</ResponseMessage>
  <ResponseType>Success</ResponseType>
</BaseResponseOfListOf{ModelName}>
```

---

## RECOMMENDED SCRAPING FLOW FOR FOOTBALL ODDS

1. **Get all sports:** `GET /api/sports?lang=en` --> Find Soccer (ID=1)
2. **Get soccer countries/tournaments:** `GET /api/sports/1/countriesandtournaments?startDate=2026-02-24`
3. **Get events for a tournament:** `GET /api/events?tournamentId=3092452&includeExtraInfo=true&includeAllStatuses=false&startDate=2026-02-24&endDate=2026-03-03&sportId=1`
4. **Get markets/odds for an event:** `GET /api/events/{eventId}/markets?byPassEventMarketCache=false`
5. **Get today's coupon shortcut:** `GET /api/sports/1/todayscoupon?betTypeId=15&lang=en`

---

## CLOUDFLARE PROTECTION

All hollywoodbets.net domains are behind Cloudflare WAF. Direct API access from scripts returns HTTP 403. To bypass:

1. Use a real browser session to obtain Cloudflare cookies (`cf_clearance`, `__cf_bm`)
2. Use browser automation tools (Selenium, Playwright) to handle the Cloudflare challenge
3. Pass the obtained cookies with subsequent API requests
4. Include realistic `User-Agent` and browser headers
5. The Angular frontend sends `Accept: application/json` to receive JSON responses

---

## KEY TOURNAMENT IDs (Soccer - from config)

**England (Country ID: 248):**
- 3092452 - Premier League
- 3092456 - Championship
- 3092553 - League One
- 3092517 - League Two
- 3092457 - FA Cup
- 3092458 - League Cup

**Spain (Country ID: 161):**
- 3092463 - La Liga
- 3092469 - Segunda Division

**Germany (Country ID: 65):**
- Listed in `priorityOrder.sports.soccer.countries`

**South Africa (Country ID: 2):**
- Multiple PSL and lower league tournaments

**UEFA Champions League (Country ID: 617)**
**UEFA Europa League (Country ID: 618)**
**UEFA Conference League (Country ID: 757)**

---

## CONTENT CMS API (Strapi)

The newer frontend also pulls content from a Strapi-based CMS:

- **Base URL:** `https://content-cms-api.hollywoodbets.net/api/v1/`
- **Platform:** `mob-south-africa-en-za` (mobile SA English)
- **Cache TTL:** 8 minutes
- **Timeout:** 2000ms

---

## DISCOVERY SOURCES

- Wayback Machine CDX API: `https://web.archive.org/cdx/search/cdx?url=betapi.hollywoodbets.net/api/*`
- Legacy frontend bundle: `https://legacy.hollywoodbets.net/main.{hash}.js`
- Config file: `https://legacy.hollywoodbets.net/assets/config/config-settings-v1.prod.json`
- Swagger UI (Mozambique): `https://betapi.hollywoodbets.co.mz/swagger/ui/index` (spec at `/swagger/docs/v1`)
