package nl.c4w.stroom.boox.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNamingStrategy
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.serializer
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Cookie
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resumeWithException

class ApiException(message: String, val status: Int? = null) : Exception(message) {
    val isUnauthorized get() = status == 401
    val isNotFound get() = status == 404

    companion object {
        fun unauthorized() =
            ApiException("Je sessie is verlopen of je inloggegevens kloppen niet. Log opnieuw in.", 401)

        /** Haalt FastAPI's `detail` (tekst of validatielijst) uit een foutantwoord. */
        fun fromResponse(status: Int, body: String): ApiException {
            if (status == 401) return unauthorized()
            val detail = runCatching { StroomJson.parseToJsonElement(body) as? JsonObject }.getOrNull()?.get("detail")
            val text = when (detail) {
                is JsonArray -> detail.firstNotNullOfOrNull { row ->
                    (row as? JsonObject)?.get("msg")?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }
                }
                null -> null
                else -> runCatching { detail.jsonPrimitive.contentOrNull }.getOrNull()?.takeIf { it.isNotBlank() }
            }
            return ApiException(text ?: "Stroom antwoordde met HTTP $status. Probeer het opnieuw.", status)
        }
    }
}

@OptIn(ExperimentalSerializationApi::class)
val StroomJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
    isLenient = true
    namingStrategy = JsonNamingStrategy.SnakeCase
}

object ServerAddress {
    /** Alleen https zonder pad, query of inloggegevens; `/api` vult de app zelf aan. */
    fun parse(text: String): HttpUrl {
        val trimmed = text.trim().trimEnd('/')
        val url = trimmed.toHttpUrlOrNull()
        if (url == null || url.scheme != "https" || url.host.isEmpty() || url.username.isNotEmpty() ||
            url.password.isNotEmpty() || url.query != null || url.fragment != null ||
            url.encodedPath != "/" || !trimmed.startsWith("https://", ignoreCase = true)
        ) {
            throw ApiException("Gebruik een geldig HTTPS-adres zonder pad, bijvoorbeeld https://stroom.c4w.nl.")
        }
        return url
    }

    fun sameOrigin(a: HttpUrl, b: HttpUrl) =
        a.scheme == b.scheme && a.host.equals(b.host, ignoreCase = true) && a.port == b.port
}

class ApiClient(
    val baseUrl: HttpUrl,
    private val session: SessionStore,
    client: OkHttpClient = defaultClient(),
) {
    // Redirects handelen we zelf af: de sessiecookie mag nooit naar een andere origin.
    private val http = client.newBuilder().followRedirects(false).followSslRedirects(false).build()
    private val account get() = baseUrl.toString()
    val hasSession get() = session.read(account) != null

    suspend inline fun <reified T> get(path: String, query: Map<String, String?> = emptyMap()): T =
        decode(serializer(), call(path, query, "GET", null))

    suspend inline fun <reified T> send(
        path: String,
        method: String = "POST",
        query: Map<String, String?> = emptyMap(),
        body: JsonElement? = null,
    ): T = decode(serializer(), call(path, query, method, body))

    fun <T> decode(serializer: KSerializer<T>, text: String): T =
        try {
            StroomJson.decodeFromString(serializer, text)
        } catch (e: Exception) {
            throw ApiException("Stroom gaf een antwoord dat de app niet begrijpt. Is de server bijgewerkt?")
        }

    suspend fun call(path: String, query: Map<String, String?>, method: String, body: JsonElement?): String {
        val builder = baseUrl.newBuilder().addPathSegment("api")
        path.split('/').filter { it.isNotEmpty() }.forEach { builder.addPathSegment(it) }
        query.forEach { (k, v) -> if (v != null) builder.addQueryParameter(k, v) }
        var url = builder.build()
        val payload = (body?.toString() ?: if (method == "GET" || method == "DELETE") null else "{}")
        val client = http.newBuilder().callTimeout(timeoutFor(path), TimeUnit.SECONDS).build()
        repeat(4) {
            val request = Request.Builder().url(url).header("Accept", "application/json").apply {
                session.read(account)?.let { header("Cookie", "$COOKIE=$it") }
                when {
                    payload != null -> method(method, payload.toRequestBody(JSON_TYPE))
                    else -> method(method, null)
                }
            }.build()
            client.newCall(request).await().use { response ->
                if (response.isRedirect) {
                    val next = response.header("Location")?.let { url.resolve(it) }
                    if (next == null || !ServerAddress.sameOrigin(next, baseUrl)) {
                        throw ApiException("Stroom stuurde door naar een ander adres; dat volgt de app niet.")
                    }
                    url = next
                    return@repeat
                }
                val text = withContext(Dispatchers.IO) { response.body?.string().orEmpty() }
                if (!response.isSuccessful) throw ApiException.fromResponse(response.code, text)
                if (path == "auth/login") storeSessionCookie(response)
                return text
            }
        }
        throw ApiException("Te veel doorverwijzingen.")
    }

    private fun storeSessionCookie(response: Response) {
        val cookie = Cookie.parseAll(response.request.url, response.headers).firstOrNull { it.name == COOKIE }
        if (cookie != null) session.save(account, cookie.value)
    }

    suspend fun login(email: String, password: String): StroomUser {
        session.delete(account)
        val result: UserResponse = send(
            "auth/login",
            body = buildJsonObject {
                put("email", email.trim())
                put("password", password)
            },
        )
        if (!hasSession) throw ApiException("De server gaf geen sessiecookie terug.")
        return result.user
    }

    suspend fun me(): StroomUser = get<UserResponse>("auth/me").user

    suspend fun logout() {
        call("auth/logout", emptyMap(), "POST", null)
        clearSession()
    }

    fun clearSession() = session.delete(account)

    suspend fun items(
        topic: String? = null,
        filter: String = "all",
        window: String = "30d",
        format: String? = null,
        limit: Int = 100,
        offset: Int = 0,
    ): List<FeedItem> = get(
        "huygens/items",
        mapOf(
            "limit" to "$limit", "offset" to "$offset", "filter" to filter,
            "window" to if (filter == "saved") null else window,
            "format" to format, "topic" to topic,
        ),
    )

    suspend fun item(id: String): FeedItem = get("huygens/items/$id")

    suspend fun setStatus(id: String, status: String): FeedItem =
        send("huygens/items/$id/status", body = buildJsonObject { put("status", status) })

    suspend fun digest(topic: String, window: String): Digest? = try {
        get("huygens/$topic/digest", mapOf("window" to window))
    } catch (e: ApiException) {
        if (e.isNotFound) null else throw e
    }

    /** De modelkeuze van de website (Beheer → Modellen) bepaalt welk model een AI-actie gebruikt. */
    suspend fun model(purpose: String): Map<String, String> {
        val settings: ModelSettings = get("admin/settings")
        val model = settings.modelDefaults[purpose]?.takeIf { it.isNotBlank() }
            ?: throw ApiException("Geen model ingesteld voor deze actie. Controleer je Stroom-instellingen.")
        return mapOf("model" to model)
    }

    companion object {
        const val COOKIE = "stroom_session"
        private val JSON_TYPE = "application/json".toMediaType()

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .cookieJar(okhttp3.CookieJar.NO_COOKIES)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)
            .build()

        fun timeoutFor(path: String): Long = when {
            path.endsWith("/lessons/distill") || path.endsWith("/expand") -> 480
            path.endsWith("/ask") || path.endsWith("/summarize") -> 240
            path.endsWith("/digest") -> 240
            else -> 30
        }
    }
}

private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) = cont.resume(response) { _, _, _ -> response.close() }
        override fun onFailure(call: Call, e: IOException) {
            if (!cont.isCancelled) {
                cont.resumeWithException(
                    ApiException("Geen verbinding met Stroom. Controleer wifi en probeer het opnieuw."),
                )
            }
        }
    })
    cont.invokeOnCancellation { runCatching { cancel() } }
}
