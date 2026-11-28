package nl.c4w.stroom.boox

import kotlinx.coroutines.test.runTest
import nl.c4w.stroom.boox.data.ApiClient
import nl.c4w.stroom.boox.data.ApiException
import nl.c4w.stroom.boox.data.FeedItem
import nl.c4w.stroom.boox.data.HuygensTopic
import nl.c4w.stroom.boox.data.MemorySessionStore
import nl.c4w.stroom.boox.data.ServerAddress
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class ApiClientTest {
    private val server = MockWebServer()
    private val sessions = MemorySessionStore()
    private lateinit var api: ApiClient

    @Before
    fun setUp() {
        server.start()
        api = ApiClient(server.url("/"), sessions)
    }

    @After
    fun tearDown() = server.shutdown()

    @Test
    fun loginStoresOnlyTheSessionCookieAndSendsItBack() = runTest {
        server.enqueue(
            MockResponse().setBody("""{"user":{"id":"u1","email":"a@b.nl"}}""")
                .addHeader("Set-Cookie", "stroom_session=geheim; HttpOnly; Path=/"),
        )
        server.enqueue(MockResponse().setBody("""{"user":{"id":"u1","email":"a@b.nl"}}"""))
        val user = api.login("a@b.nl", "wachtwoord")
        assertEquals("u1", user.id)
        val login = server.takeRequest()
        assertEquals("/api/auth/login", login.path)
        assertTrue(login.body.readUtf8().contains("\"password\":\"wachtwoord\""))
        api.me()
        assertEquals("stroom_session=geheim", server.takeRequest().getHeader("Cookie"))
    }

    @Test
    fun refusesRedirectToAnotherOrigin() = runTest {
        server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "https://elders.example/api/x"))
        try {
            api.item("1")
            fail("Redirect naar andere origin hoort te falen")
        } catch (e: ApiException) {
            assertTrue(e.message!!.contains("ander adres"))
        }
    }

    @Test
    fun followsSameOriginRedirect() = runTest {
        server.enqueue(MockResponse().setResponseCode(307).addHeader("Location", "/api/huygens/items/2"))
        server.enqueue(MockResponse().setBody("""{"id":"2","title":"Twee","source_name":"Bron","status":"pinned"}"""))
        val item = api.item("1")
        assertEquals("Twee", item.title)
        assertTrue(item.isSaved)
    }

    @Test
    fun mapsFastApiErrors() = runTest {
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"Ongeldige URL"}"""))
        server.enqueue(MockResponse().setResponseCode(422).setBody("""{"detail":[{"msg":"veld ontbreekt"}]}"""))
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Niet ingelogd"}"""))
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"Topic not found"}"""))
        assertEquals("Ongeldige URL", runCatching { api.me() }.exceptionOrNull()?.message)
        assertEquals("veld ontbreekt", runCatching { api.me() }.exceptionOrNull()?.message)
        assertTrue((runCatching { api.me() }.exceptionOrNull() as ApiException).isUnauthorized)
        assertNull(api.digest("tech", "daily"))
    }

    @Test
    fun decodesListsAndToleratesUnknownFieldsAndBrokenSegments() = runTest {
        server.enqueue(
            MockResponse().setBody(
                """{"slug":"tech","name":"Technologie","rails":[{"format":"article","items":[
                {"id":"a","title":"A","source_id":"s","source_name":"Bron","quality_score":7,"nieuw_veld":true,
                 "has_summary":true}]}]}""",
            ),
        )
        val topic: HuygensTopic = api.get("huygens/tech")
        val item = topic.orderedRails.single().items.single()
        assertEquals(7.0, item.qualityScore!!, 0.0)
        assertTrue(item.hasSummaryText)

        server.enqueue(
            MockResponse().setBody(
                """{"id":"p","title":"P","format":"podcast","transcript_segments":[{"start":1,"end":2,"text":"ok"},{"start":"x"}]}""",
            ),
        )
        val podcast: FeedItem = api.item("p")
        assertEquals(1, podcast.segments.size)
    }

    @Test
    fun serverAddressMustBePlainHttps() {
        assertEquals("stroom.c4w.nl", ServerAddress.parse(" https://stroom.c4w.nl/ ").host)
        listOf("http://stroom.c4w.nl", "https://stroom.c4w.nl/api", "https://user:pw@stroom.c4w.nl", "stroom.c4w.nl", "https://x.nl?a=1")
            .forEach { bad ->
                assertTrue(bad, runCatching { ServerAddress.parse(bad) }.isFailure)
            }
    }
}
