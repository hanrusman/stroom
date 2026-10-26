import XCTest

final class NavigationTests: XCTestCase {
    @MainActor func testNativeNavigationAndReader() throws {
        let app = XCUIApplication(); app.launchArguments = ["--demo"]; app.launch()
        XCTAssertTrue(app.staticTexts["Volg je nieuwsgierigheid."].waitForExistence(timeout: 10))
        let home = XCTAttachment(screenshot: app.screenshot()); home.name = "Stroom-feed"; home.lifetime = .keepAlways; add(home)
        app.buttons["Wat verandert er als AI echt met je meedenkt?"].tap()
        XCTAssertTrue(app.staticTexts["Een nieuwe manier van samenwerken"].waitForExistence(timeout: 5))
        app.buttons["Bron"].tap()
        XCTAssertTrue(app.staticTexts["Een gesprek over nieuwsgierigheid, creativiteit en de volgende stap in kunstmatige intelligentie."].exists)
        app.buttons["Lessen"].tap()
        XCTAssertTrue(app.staticTexts["Nog geen lessen bij dit item. Maak eerst een samenvatting."].waitForExistence(timeout: 5))
        app.buttons["Gereed"].tap()
        app.tabBars.buttons["Luisteren"].tap()
        XCTAssertTrue(app.staticTexts["Goed gezelschap voor onderweg."].waitForExistence(timeout: 5))
        app.tabBars.buttons["Bibliotheek"].tap()
        XCTAssertTrue(app.staticTexts["Jouw eigen verzameling"].waitForExistence(timeout: 5))
        app.tabBars.buttons["Meer"].tap()
        app.buttons["Instellingen en meldingen"].tap()
        XCTAssertTrue(app.staticTexts["Maak ruimte voor wat telt."].waitForExistence(timeout: 5))
    }
    @MainActor func testBothSwipeDirectionsQueueArchiveAndUndo() throws {
        let app = XCUIApplication(); app.launchArguments = ["--demo"]; app.launch()
        let title = "Wat verandert er als AI echt met je meedenkt?"
        XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 10))
        app.buttons[title].swipeLeft()
        if app.buttons["queue-demo-1"].exists { app.buttons["queue-demo-1"].tap() }
        XCTAssertTrue(app.staticTexts["Toegevoegd aan je wachtrij"].waitForExistence(timeout: 5))
        app.tabBars.buttons["Wachtrij"].tap()
        XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 5))
        let queued = XCTAttachment(screenshot: app.screenshot()); queued.name = "Stroom-wachtrij"; queued.lifetime = .keepAlways; add(queued)
        app.buttons[title].swipeRight()
        if app.buttons["archive-demo-1"].exists { app.buttons["archive-demo-1"].tap() }
        XCTAssertTrue(app.staticTexts["Ruimte voor je volgende idee"].waitForExistence(timeout: 5))
        app.buttons["Herstel"].tap()
        XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 5))
    }
}
