package com.macrofinder.app.ui

/**
 * Where the user is. A back stack of routes rather than a navigation library:
 * a handful of destinations, and a plain list is testable on the JVM and
 * trivially saveable across process death as strings.
 */
sealed interface Route {
    val key: String

    data object Deals : Route { override val key = "deals" }
    data object Search : Route { override val key = "search" }
    data object Meals : Route { override val key = "meals" }
    data object Following : Route { override val key = "following" }
    data object SavedMeals : Route { override val key = "saved" }
    data object About : Route { override val key = "about" }
    data class Product(val id: String) : Route { override val key = "product:$id" }
    data class Customise(val templateKey: String) : Route { override val key = "customise:$templateKey" }

    companion object {
        val TABS = listOf(Deals, Search, Meals, Following)

        fun parse(key: String): Route = when {
            key.startsWith("product:") -> Product(key.removePrefix("product:"))
            key.startsWith("customise:") -> Customise(key.removePrefix("customise:"))
            else -> listOf(Deals, Search, Meals, Following, SavedMeals, About)
                .firstOrNull { it.key == key } ?: Deals
        }
    }
}

fun tabLabel(route: Route): String = when (route) {
    Route.Deals -> "Aanbod"
    Route.Search -> "Zoeken"
    Route.Meals -> "Maaltijden"
    Route.Following -> "Gevolgd"
    else -> ""
}

/** Push a route. Selecting a tab resets the stack to that tab. */
fun List<Route>.push(route: Route): List<Route> =
    if (route in Route.TABS) listOf(route) else this + route

fun List<Route>.pop(): List<Route> = if (size > 1) dropLast(1) else this

/** The tab a stack belongs to, for the bottom bar. */
fun List<Route>.tab(): Route = firstOrNull { it in Route.TABS } ?: Route.Deals
