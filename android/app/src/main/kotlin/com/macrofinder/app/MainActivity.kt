package com.macrofinder.app

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.livedata.observeAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.runtime.CompositionLocalProvider
import kotlin.math.min
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.macrofinder.app.data.SavedMealsStore
import com.macrofinder.app.data.following.PromoNotifier
import com.macrofinder.app.data.sync.CatalogueSyncWorker
import com.macrofinder.app.data.sync.HaltState
import com.macrofinder.app.ui.CatalogueSyncState
import com.macrofinder.app.ui.CatalogueViewModel
import com.macrofinder.app.ui.MacroFinderViewModel
import com.macrofinder.app.ui.Route
import com.macrofinder.app.ui.components.Hairline
import com.macrofinder.app.ui.components.TextTabs
import com.macrofinder.app.ui.pop
import com.macrofinder.app.ui.push
import com.macrofinder.app.ui.screens.AboutScreen
import com.macrofinder.app.ui.screens.CustomiseScreen
import com.macrofinder.app.ui.screens.DealsScreen
import com.macrofinder.app.ui.screens.FollowingScreen
import com.macrofinder.app.ui.screens.MealsScreen
import com.macrofinder.app.ui.screens.ProductScreen
import com.macrofinder.app.ui.screens.SavedMealsScreen
import com.macrofinder.app.ui.screens.SearchScreen
import com.macrofinder.app.ui.tab
import com.macrofinder.app.ui.tabLabel
import com.macrofinder.app.ui.theme.MF
import com.macrofinder.app.ui.theme.MacroFinderTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Edge to edge, so the IME and system bar insets are real and the
        // layout can pad for them itself.
        enableEdgeToEdge()
        // Idempotent (KEEP), so this re-asserts the schedule rather than stacking jobs.
        CatalogueSyncWorker.schedule(this)
        setContent {
            MacroFinderTheme {
                MacroFinderApp()
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MacroFinderApp(
    meals: MacroFinderViewModel = viewModel(),
    catalogue: CatalogueViewModel = viewModel(),
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val savedMeals = remember { SavedMealsStore(context) }
    val mealsState by meals.state.collectAsState()

    // The back stack, saved as strings so it survives process death.
    var stackKeys by rememberSaveable { mutableStateOf(listOf(Route.Deals.key)) }
    val stack = stackKeys.map(Route::parse)
    fun go(route: Route) { stackKeys = stack.push(route).map { it.key } }
    fun back() { stackKeys = stack.pop().map { it.key } }
    BackHandler(enabled = stack.size > 1) { back() }

    LaunchedEffect(Unit) { savedMeals.meals.collect { meals.setSavedMeals(it) } }
    LaunchedEffect(mealsState.fallbackDeals) { catalogue.setFallback(mealsState.fallbackDeals) }

    // The sync runs whether or not the app is open; the UI watches WorkManager.
    val workManager = remember { WorkManager.getInstance(context) }
    val periodic by workManager.getWorkInfosForUniqueWorkLiveData(CatalogueSyncWorker.PERIODIC_NAME)
        .observeAsState(emptyList())
    val oneOff by workManager.getWorkInfosForUniqueWorkLiveData(CatalogueSyncWorker.ONE_OFF_NAME)
        .observeAsState(emptyList())
    // A manual refresh is what the user is waiting on, so it wins while it's live.
    val manual = oneOff.firstOrNull()?.takeIf { !it.state.isFinished || periodic.isEmpty() }
    val latest = manual ?: periodic.firstOrNull() ?: oneOff.firstOrNull()
    val workSync = CatalogueSyncState.fromWorkInfo(latest, oneOff = latest != null && latest == oneOff.firstOrNull())
    // The kill switch outlives the job that saw it; see HaltState.
    val haltMessage = remember(latest?.state, latest?.outputData) { HaltState.message(context) }
    val sync = if (haltMessage != null && !workSync.running)
        CatalogueSyncState(halted = true, message = haltMessage) else workSync
    LaunchedEffect(latest?.state, latest?.outputData) {
        if (latest?.state == WorkInfo.State.SUCCEEDED || latest?.state == WorkInfo.State.ENQUEUED) {
            catalogue.reload()
        }
    }
    val refresh = {
        CatalogueSyncWorker.syncNow(context)
        meals.refresh()
    }

    // Milestone 26: ask for notifications the first time someone follows a product.
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    val onFollow: (String, Boolean) -> Unit = { id, follow ->
        catalogue.toggleFollow(id)
        if (follow && Build.VERSION.SDK_INT >= 33 && !PromoNotifier.allowed(context)) {
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    val openProduct: (String) -> Unit = { id -> catalogue.openDetail(id); go(Route.Product(id)) }

    val typing = WindowInsets.isImeVisible
    Column(Modifier.fillMaxSize().background(MF.tokens.paper).statusBarsPadding()) {
        Box(Modifier.weight(1f).fillMaxWidth().then(if (typing) Modifier.imePadding() else Modifier)) {
            when (val route = stack.last()) {
                Route.Deals -> DealsScreen(catalogue, sync, refresh, openProduct, onAbout = { go(Route.About) })
                Route.Search -> SearchScreen(catalogue, openProduct)
                Route.Meals -> MealsScreen(
                    meals,
                    onCustomise = { key -> meals.customise(key); go(Route.Customise(key)) },
                    onSaved = { go(Route.SavedMeals) },
                )
                Route.Following -> FollowingScreen(catalogue, openProduct)
                Route.About -> AboutScreen(catalogue, sync, mealsState.generatedAt, onBack = ::back)
                Route.SavedMeals -> SavedMealsScreen(
                    meals, onBack = ::back,
                    onOpen = { meal ->
                        meals.openSaved(meal)
                        meal.templateKey?.let { go(Route.Customise(it)) }
                    },
                    onDelete = { id -> scope.launch { savedMeals.delete(id) } },
                )
                is Route.Product -> {
                    LaunchedEffect(route.id) { catalogue.openDetail(route.id) }
                    ProductScreen(catalogue, onBack = ::back, onFollow = onFollow)
                }
                is Route.Customise -> {
                    LaunchedEffect(route.templateKey) {
                        if (meals.currentTemplate()?.key != route.templateKey) meals.customise(route.templateKey)
                    }
                    CustomiseScreen(
                        meals,
                        onBack = { meals.back(); back() },
                        onSave = { name -> scope.launch { savedMeals.save(meals.buildSavedMeal(name)) } },
                    )
                }
            }
        }
        // Out of the way while typing, so the keyboard doesn't push it up the screen.
        if (!typing) BottomBar(current = stack.tab(), onSelect = ::go)
    }
}

/** Four text tabs, no icons: DESIGN.md prefers a word to a stock glyph. */
@Composable
private fun BottomBar(current: Route, onSelect: (Route) -> Unit) {
    // Four words across a phone: cap the font scale here, as Material's own
    // navigation bar does, so "Maaltijden" never breaks mid-word at 200%.
    val density = LocalDensity.current
    CompositionLocalProvider(
        LocalDensity provides Density(density.density, min(density.fontScale, 1.3f)),
    ) {
        Column(Modifier.fillMaxWidth().background(MF.tokens.card).navigationBarsPadding()) {
            Hairline()
            TextTabs(
                options = Route.TABS,
                selected = current,
                label = ::tabLabel,
                onSelect = onSelect,
                scrollable = false,
                evenly = true,
            )
        }
    }
}
