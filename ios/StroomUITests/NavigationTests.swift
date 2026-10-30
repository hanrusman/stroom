import XCTest

final class NavigationTests: XCTestCase {
  @MainActor func testCuratedHomeTopicSwitchAndFullArticle() throws {
    let app = XCUIApplication()
    app.launchArguments = ["--demo", "--reset-topic"]
    app.launch()
    XCTAssertTrue(app.buttons["topic-ai"].waitForExistence(timeout: 10))
    XCTAssertTrue(app.staticTexts["Vandaag"].exists)
    let light = XCTAttachment(screenshot: app.screenshot())
    light.name = "Fase1-home-licht"
    light.lifetime = .keepAlways
    add(light)
    app.buttons["topic-science"].tap()
    app.swipeUp()
    app.buttons["De stille revolutie in onze oceanen"].tap()
    XCTAssertTrue(app.buttons["Grotere letters"].waitForExistence(timeout: 5))
    app.swipeUp()
    XCTAssertTrue(
      app.staticTexts[
        "Dit is de volledige artikeltekst, met meer context dan het korte RSS-uittreksel."
      ].waitForExistence(timeout: 5))
    XCTAssertFalse(app.buttons["Transcript"].exists)
    let reader = XCTAttachment(screenshot: app.screenshot())
    reader.name = "Fase1-reader-licht"
    reader.lifetime = .keepAlways
    add(reader)
    app.terminate()
    app.launchArguments = ["--demo", "--dark"]
    app.launch()
    XCTAssertTrue(app.buttons["topic-science"].waitForExistence(timeout: 10))
    XCTAssertTrue(app.buttons["topic-science"].isSelected)
    let dark = XCTAttachment(screenshot: app.screenshot())
    dark.name = "Fase1-home-donker"
    dark.lifetime = .keepAlways
    add(dark)
  }
  @MainActor func testCompanionLessonsAndQuestionSuggestions() throws {
    for mode in ["--light", "--dark"] {
      let app = XCUIApplication()
      app.launchArguments = ["--demo", "--reset-topic", "--companion-fixtures", mode]
      app.launch()
      XCTAssertTrue(app.buttons["topic-ai"].waitForExistence(timeout: 10))
      app.swipeUp()
      app.buttons["Wat verandert er als AI echt met je meedenkt?"].tap()
      app.buttons["Lessen"].tap()
      XCTAssertTrue(app.staticTexts["Stel eerst een betere vraag"].waitForExistence(timeout: 5))
      app.swipeUp()
      XCTAssertTrue(app.buttons["Verdiep deze les"].exists)
      let shot = XCTAttachment(screenshot: app.screenshot())
      shot.name = "Fase2-lessen-" + mode
      shot.lifetime = .keepAlways
      add(shot)
      app.swipeDown()
      app.buttons["Vraag"].tap()
      XCTAssertTrue(app.buttons["Welk bewijs draagt de auteur aan?"].waitForExistence(timeout: 5))
      app.buttons["Welk bewijs draagt de auteur aan?"].tap()
      app.swipeUp()
      let input = app.descendants(matching: .any)["question-input"].firstMatch
      XCTAssertTrue(input.waitForExistence(timeout: 5))
      XCTAssertEqual(input.value as? String, "Welk bewijs draagt de auteur aan?")
      app.terminate()
    }
  }
  @MainActor func testPlanningScoreTopicsAndArchiveRail() throws {
    let app = XCUIApplication()
    app.launchArguments = ["--demo", "--reset-topic"]
    app.launch()
    XCTAssertTrue(app.buttons["topic-science"].waitForExistence(timeout: 10))
    app.buttons["topic-science"].tap()
    app.swipeUp()
    app.buttons["De stille revolutie in onze oceanen"].tap()
    app.buttons["Plan"].tap()
    app.buttons["Later (geen datum)"].tap()
    XCTAssertTrue(app.staticTexts["Later · geen datum"].waitForExistence(timeout: 5))
    app.buttons["Plan"].tap()
    app.buttons["Wis planning"].tap()
    XCTAssertFalse(app.staticTexts["Later · geen datum"].exists)
    app.buttons["Plan"].swipeLeft()
    app.buttons["Score en onderwerpen"].tap()
    XCTAssertTrue(app.buttons["Score opslaan"].waitForExistence(timeout: 5))
    app.buttons["Score opslaan"].tap()
    XCTAssertTrue(app.staticTexts["Score opgeslagen"].waitForExistence(timeout: 5))
    app.buttons["AI & technologie, niet toegevoegd"].tap()
    XCTAssertTrue(app.buttons["AI & technologie, toegevoegd"].waitForExistence(timeout: 5))
    let shot = XCTAttachment(screenshot: app.screenshot())
    shot.name = "Fase3-curatie-licht"
    shot.lifetime = .keepAlways
    add(shot)
    app.buttons["curation-done"].tap()
    app.buttons["Gereed"].tap()
    app.swipeUp()
    app.buttons["archive-rail-article"].tap()
    app.buttons["Archiveer 1 artikelen"].tap()
    XCTAssertTrue(app.staticTexts["1 items gearchiveerd"].waitForExistence(timeout: 5))
    XCTAssertFalse(app.buttons["Herstel"].exists)
    let gone = NSPredicate(format: "exists == false")
    expectation(for: gone, evaluatedWith: app.buttons["De stille revolutie in onze oceanen"])
    waitForExpectations(timeout: 5)
    app.terminate()
  }
  @MainActor func testNativeSubmissionTipsAndLessons() throws {
    for mode in ["--light", "--dark"] {
      let app = XCUIApplication()
      app.launchArguments = ["--demo", "--reset-topic", mode]
      app.launch()
      XCTAssertTrue(app.tabBars.buttons["Meer"].waitForExistence(timeout: 10))
      app.tabBars.buttons["Meer"].tap()
      app.buttons["Content insturen"].tap()
      let url = app.textFields["submit-url"]
      XCTAssertTrue(url.waitForExistence(timeout: 5))
      url.tap()
      url.typeText("https://example.com/article")
      app.buttons["Haal titel en beschrijving op"].tap()
      XCTAssertTrue(
        app.descendants(matching: .any)["submit-title"].firstMatch.waitForExistence(timeout: 5))
      app.swipeUp()
      let shot = XCTAttachment(screenshot: app.screenshot())
      shot.name = "Fase4-insturen-" + mode
      shot.lifetime = .keepAlways
      add(shot)
      app.buttons["Stuur naar Stroom"].tap()
      XCTAssertTrue(app.staticTexts["Toegevoegd aan Stroom"].waitForExistence(timeout: 5))
      app.buttons["Gereed"].tap()
      app.buttons["Tips uit podcasts en video’s"].tap()
      let tip = app.staticTexts["Een wereld vol vragen"]
      XCTAssertTrue(tip.waitForExistence(timeout: 5))
      tip.tap()
      XCTAssertTrue(app.staticTexts["De gast"].waitForExistence(timeout: 5))
      let tips = XCTAttachment(screenshot: app.screenshot())
      tips.name = "Fase4-tips-" + mode
      tips.lifetime = .keepAlways
      add(tips)
      app.terminate()
    }
  }
  @MainActor func testDarkCurationAndNativeLessonsList() throws {
    let app = XCUIApplication()
    app.launchArguments = ["--demo", "--reset-topic", "--dark"]
    app.launch()
    XCTAssertTrue(app.tabBars.buttons["Meer"].waitForExistence(timeout: 10))
    app.tabBars.buttons["Meer"].tap()
    app.buttons["Alle lessen"].tap()
    XCTAssertTrue(app.staticTexts["Stel eerst een betere vraag"].waitForExistence(timeout: 5))
    app.swipeUp()
    app.buttons["Wat verandert er als AI echt met je meedenkt?"].tap()
    app.buttons["Plan"].swipeLeft()
    app.buttons["Score en onderwerpen"].tap()
    XCTAssertTrue(app.buttons["Score opslaan"].waitForExistence(timeout: 5))
    let shot = XCTAttachment(screenshot: app.screenshot())
    shot.name = "Fase3-curatie-donker"
    shot.lifetime = .keepAlways
    add(shot)
    app.terminate()
  }
  @MainActor func testNativeNavigationAndReader() throws {
    let app = XCUIApplication()
    app.launchArguments = ["--demo", "--reset-topic"]
    app.launch()
    XCTAssertTrue(app.staticTexts["Volg je nieuwsgierigheid."].waitForExistence(timeout: 10))
    let home = XCTAttachment(screenshot: app.screenshot())
    home.name = "Stroom-feed"
    home.lifetime = .keepAlways
    add(home)
    app.swipeUp()
    app.buttons["Wat verandert er als AI echt met je meedenkt?"].tap()
    XCTAssertTrue(app.staticTexts["Een nieuwe manier van samenwerken"].waitForExistence(timeout: 5))
    app.buttons["Bron"].tap()
    XCTAssertTrue(
      app.staticTexts[
        "Een gesprek over nieuwsgierigheid, creativiteit en de volgende stap in kunstmatige intelligentie."
      ].exists)
    app.buttons["Lessen"].tap()
    XCTAssertTrue(
      app.staticTexts["Nog geen lessen bij dit item. Maak eerst een samenvatting."]
        .waitForExistence(timeout: 5))
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
    let app = XCUIApplication()
    app.launchArguments = ["--demo", "--reset-topic"]
    app.launch()
    let title = "Wat verandert er als AI echt met je meedenkt?"
    XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 10))
    app.swipeUp()
    app.buttons[title].swipeLeft()
    if app.buttons["queue-demo-1"].exists { app.buttons["queue-demo-1"].tap() }
    XCTAssertTrue(app.staticTexts["Toegevoegd aan je wachtrij"].waitForExistence(timeout: 5))
    app.tabBars.buttons["Wachtrij"].tap()
    XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 5))
    let queued = XCTAttachment(screenshot: app.screenshot())
    queued.name = "Stroom-wachtrij"
    queued.lifetime = .keepAlways
    add(queued)
    app.buttons[title].swipeRight()
    if app.buttons["archive-demo-1"].exists { app.buttons["archive-demo-1"].tap() }
    XCTAssertTrue(app.staticTexts["Ruimte voor je volgende idee"].waitForExistence(timeout: 5))
    app.buttons["Herstel"].tap()
    XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 5))
  }
}
