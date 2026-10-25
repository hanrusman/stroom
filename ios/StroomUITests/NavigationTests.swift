import XCTest

final class NavigationTests: XCTestCase {
    @MainActor func testNativeNavigationAndReader() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--demo"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Volg je nieuwsgierigheid."].waitForExistence(timeout: 10))
        let home = XCTAttachment(screenshot: app.screenshot()); home.name = "Stroom-feed"; home.lifetime = .keepAlways; add(home)
        app.buttons["Wat verandert er als AI echt met je meedenkt?"].tap()
        XCTAssertTrue(app.staticTexts["Een nieuwe manier van samenwerken"].waitForExistence(timeout: 5))
        app.buttons["Gereed"].tap()
        app.tabBars.buttons["Luisteren"].tap()
        XCTAssertTrue(app.staticTexts["Goed gezelschap\nvoor onderweg."].waitForExistence(timeout: 5))
        app.tabBars.buttons["Bibliotheek"].tap()
        XCTAssertTrue(app.staticTexts["Jouw eigen verzameling"].waitForExistence(timeout: 5))
        app.tabBars.buttons["Instellingen"].tap()
        XCTAssertTrue(app.staticTexts["Maak ruimte voor wat telt."].waitForExistence(timeout: 5))
        XCTAssertTrue(app.switches["Nieuwe inhoud melden"].exists)
        let settings = XCTAttachment(screenshot: app.screenshot()); settings.name = "Stroom-instellingen"; settings.lifetime = .keepAlways; add(settings)
    }
}
