"""
translations.py
Provides a simple translation layer for Memento's GUI.

Usage:
    from translations import t, set_lang, get_lang

    t("Save")        # returns "Salva" when lang == "it", else "Save"
    set_lang("it")   # switch to Italian
    set_lang("en")   # switch back to English
"""

_lang: dict = {"v": "en"}

ITALIAN: dict = {
    # ── main_app.py ──────────────────────────────────────────────────────────
    "About Memento":            "Informazioni su Memento",
    "Version":                  "Versione",
    "Build date":               "Data build",
    "Author":                   "Autore",
    "Close":                    "Chiudi",
    "User Manual":              "Manuale utente",
    "The user manual will be available in a future release.":
        "Il manuale utente sarà disponibile in una versione futura.",
    "Release Notes":            "Note di rilascio",
    "Release notes not found.": "File note di rilascio non trovato.",
    "Installation Path":         "Percorso d'installazione",
    "Installation Path…":        "Percorso d'installazione…",
    "Browse…":                  "Sfoglia…",
    "Cancel":                   "Annulla",
    "Save":                     "Salva",
    "Toggle theme":             "Cambia tema",
    "Settings":                 "Impostazioni",
    "Help":                     "Aiuto",
    "About":                    "Informazioni",
    "Command Bar…":             "Barra comandi…",
    "Command Bar Position":     "Posizione barra comandi",
    "Choose where the action buttons appear:":
        "Scegli dove appaiono i pulsanti azione:",
    "Position":                 "Posizione",
    "Apply":                    "Applica",
    "Language…":                "Lingua…",
    "Language":                 "Lingua",
    "Select language:":         "Seleziona lingua:",
    "English":                  "Inglese",
    "Italian":                  "Italiano",
    "Select Installation Folder": "Seleziona cartella d'installazione",
    "Back to list":             "Torna alla lista",
    # CmdBar position options
    "Top":                      "Alto",
    "Bottom":                   "Basso",
    "Left":                     "Sinistra",
    "Right":                    "Destra",
    # ── toolbar tooltips ─────────────────────────────────────────────────────
    "New Task":                 "Nuovo Task",
    "Edit Task":                "Modifica Task",
    "Delete Task":              "Elimina Task",
    "Status Chart":             "Grafico stati",
    "Calendar":                 "Calendario",
    "Filter":                   "Filtra",
    "Search":                   "Cerca",
    "New Design":               "Nuovo Design",
    "Edit Design":              "Modifica Design",
    "Delete Design":            "Elimina Design",
    # ── task_tracker.py & design_tracker.py ──────────────────────────────────
    "Title":                    "Titolo",
    "Title:":                   "Titolo:",
    "Project":                  "Progetto",
    "Project:":                 "Progetto:",
    "Status":                   "Stato",
    "Status:":                  "Stato:",
    "Alarm":                    "Allarme",
    "Alarm:":                   "Allarme:",
    "Alarm fired:":             "Allarme scattato:",
    "Description":              "Descrizione",
    "Pick date":                "Scegli data",
    "Clear alarm":              "Rimuovi allarme",
    "No alarm":                 "Nessun allarme",
    "Related Tasks":            "Task Correlati",
    "Related Designs":          "Design Correlati",
    "Files":                    "File",
    "Add relation":             "Aggiungi relazione",
    "Add design relation":      "Aggiungi relazione Design",
    "Add task relation":        "Aggiungi relazione Task",
    "Remove":                   "Rimuovi",
    "Remove relation":          "Rimuovi relazione",
    "Remove attachment":        "Rimuovi allegato",
    "Remove tag":               "Rimuovi tag",
    "Add tag":                  "Aggiungi tag",
    "Edit":                     "Modifica",
    "Edit description":         "Modifica descrizione",
    "Save description":         "Salva descrizione",
    "Cancel editing":           "Annulla modifica",
    "Text color":               "Colore testo",
    "Delete entry":             "Elimina voce",
    "Attach file to this entry": "Allega file a questa voce",
    "Attach File":              "Allega file",
    "History":                  "Cronologia",
    "Tags":                     "Tag",
    "No tags found":            "Nessun tag trovato",
    "Filter active":            "Filtro attivo",
    "Clear":                    "Azzera",
    "Close search":             "Chiudi ricerca",
    "Search\u2026":             "Cerca\u2026",
    "Period":                   "Periodo",
    "Status Distribution":      "Distribuzione stati",
    "Double-click to edit":     "Doppio click per modificare",
    "Alarm Calendar":           "Calendario allarmi",
    "Next year":                "Anno successivo",
    "Previous year":            "Anno precedente",
    "Previous":                 "Precedente",
    "Next":                     "Successivo",
    "Today":                    "Oggi",
    "Reset":                    "Reimposta",
    "Delete":                   "Elimina",
    "Filter Tasks":             "Filtra Task",
    "Filter Designs":           "Filtra Design",
    "Are you sure you want to permanently delete this task?":
        "Sei sicuro di voler eliminare definitivamente questo task?",
    "Are you sure you want to permanently delete this design?":
        "Sei sicuro di voler eliminare definitivamente questo design?",
    "No data for the selected filters.":
        "Nessun dato per i filtri selezionati.",
    "No tasks yet \u2014 use the  +  button in the toolbar to create one.":
        "Nessun task ancora \u2014 usa il pulsante  +  nella barra degli strumenti per crearne uno.",
    "No designs yet \u2014 use the  +  button in the toolbar to create one.":
        "Nessun design ancora \u2014 usa il pulsante  +  nella barra degli strumenti per crearne uno.",
    "Opened":                   "Aperto",
    "Modified":                 "Modificato",
    "Closed":                   "Chiuso",
    "Name":                     "Nome",
    "Name:":                    "Nome:",
    "Board":                    "Scheda",
    "Board:":                   "Scheda:",
    "Revision":                 "Revisione",
    "Revision:":                "Revisione:",
    "Category":                 "Categoria",
    "Category:":                "Categoria:",
    "Function":                 "Funzione",
    "Function:":                "Funzione:",
    "Specify category":         "Specifica categoria",
    "Specify function":         "Specifica funzione",
    "Specify\u2026":            "Specifica\u2026",
    # alarm before options
    "At alarm time":            "All'orario dell'allarme",
    "5 min before":             "5 min prima",
    "15 min before":            "15 min prima",
    "30 min before":            "30 min prima",
    "1 hour before":            "1 ora prima",
    "2 hours before":           "2 ore prima",
    # inline error messages
    "Enter a valid number":     "Inserisci un numero valido",
    "Already added":            "Già aggiunto",
    "File already attached":    "File già allegato",
    "is already attached to":   "è già allegato a",
    "update":                   "aggiornamento",
    "Task not found":           "Task non trovato",
    "Design not found":         "Design non trovato",
    "Invalid format \u2014 use YYYY-MM-DD and HH:MM":
        "Formato non valido \u2014 usa AAAA-MM-GG e HH:MM",
    # chart period labels
    "Last Day":                 "Ultimo giorno",
    "Last Week":                "Ultima settimana",
    "Last Month":               "Ultimo mese",
    "Last Year":                "Ultimo anno",
    "All Projects":             "Tutti i progetti",
    # calendar view labels
    "Day":                      "Giorno",
    "Week":                     "Settimana",
    "Month":                    "Mese",
    # description hints
    "Task description\u2026":   "Descrizione del task\u2026",
    "Design description\u2026": "Descrizione del design\u2026",
    "Write an update\u2026":    "Scrivi un aggiornamento\u2026",
    # history entry button
    "Save update":              "Salva aggiornamento",
    "New update":               "Nuovo aggiornamento",
    # relative date labels
    "Today":                    "Oggi",
    "Yesterday":                "Ieri",
    "days ago":                 "giorni fa",
    # auto-start
    "Auto-start\u2026":          "Avvio Automatico\u2026",
    "Auto-start":               "Avvio Automatico",
    "Enable automatic startup at system boot":
        "Abilita l'esecuzione automatica all'avvio del sistema",
    "If enabled, Memento's system-tray process will start automatically when Windows boots.":
        "Se abilitato, il processo dell'icona di sistema di Memento si avvier\u00e0 automaticamente all'avvio di Windows.",
    # wizard navigation
    "Step":                     "Passo",
    "of":                       "di",
    "Back":                     "Indietro",
    "Next":                     "Avanti",
    "Finish":                   "Fine",
    # wizard header
    "First-time setup wizard":  "Procedura guidata iniziale",
    # wizard steps
    "Language Selection":       "Selezione lingua",
    "Choose your preferred language":
        "Scegli la tua lingua preferita",
    "Theme Selection":          "Selezione tema",
    "Choose your preferred display mode":
        "Scegli la modalit\u00e0 di visualizzazione preferita",
    "Dark Mode  \U0001f319":    "Modalit\u00e0 scura  \U0001f319",
    "Light Mode  \u2600\ufe0f": "Modalit\u00e0 chiara  \u2600\ufe0f",
    "Installation Folder":      "Cartella d'installazione",
    "Select where Memento will save its files":
        "Seleziona dove Memento salver\u00e0 i suoi file",
    "A \"Memento\" folder will be created at the chosen path, containing TaskTracker and DesignTracker subfolders.":
        "Una cartella \"Memento\" verr\u00e0 creata nel percorso scelto, contenente le sottocartelle TaskTracker e DesignTracker.",
    "Starting Application":     "Applicazione di avvio",
    "Choose which tracker to open at startup":
        "Scegli quale modulo aprire all'avvio",
}


def set_lang(lang: str) -> None:
    """Set the active language ('en' or 'it')."""
    _lang["v"] = lang


def get_lang() -> str:
    """Return the active language code."""
    return _lang["v"]


def t(key: str) -> str:
    """Return the Italian translation of *key* when lang=='it', else *key* itself."""
    if _lang["v"] == "it":
        return ITALIAN.get(key, key)
    return key
