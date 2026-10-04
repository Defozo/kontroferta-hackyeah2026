"""Build an honest submission summary from executed machine reports only."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path):
    target = ROOT/path
    return json.loads(target.read_text(encoding="utf-8")) if target.exists() else None


def latest(*paths):
    return next((path for path in paths if (ROOT/path).exists()), paths[-1])


def main():
    extraction_path = latest("results/evaluation-v9-linux/report-all.json", "results/evaluation-v8-linux/report-all.json", "results/evaluation-v6/report-all.json")
    methods_path = latest("results/methods-v9/report.json", "results/methods-v8/report.json", "results/methods-v6/report.json")
    demo_path = latest("results/live-demo-v9-linux/report.json", "results/live-demo-v8-linux/report.json", "results/live-demo-v6/report.json")
    performance_path = latest("results/performance-v9-linux/report.json", "results/performance-v8-linux/report.json", "results/performance-v6/report.json")
    uuid_path = latest("results/live-uuid-v9-linux.json", "results/live-uuid-v8-linux.json")
    extraction = read(extraction_path)
    methods = read(methods_path)
    demo = read(demo_path)
    performance = read(performance_path)
    windows_performance = read("results/performance-v6/report.json")
    uuid_probe = read(uuid_path)
    linux_environment = read("results/execution-environment-v9-linux.json")
    normalizer = read("results/normalizer-v7-targeted/report-all.json")
    team = json.loads((ROOT.parent/"TEAM.json").read_text(encoding="utf-8"))
    if performance:
        predictions = [json.loads(path.read_text(encoding="utf-8")) for path in (ROOT/Path(performance_path).parent).glob("batch-*.json")]
        prices, usage = [], {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
        for prediction in predictions:
            trace = prediction.get("extraction", {}).get("trace", prediction.get("error", {}).get("trace", {}))
            if prediction.get("error", {}).get("code") == "parser_timeout":
                prices.append(Decimal(0))  # No provider call was made after this parser failure.
            elif trace.get("estimated_cost_usd") is not None:
                prices.append(Decimal(trace["estimated_cost_usd"]))
            for key in usage:
                usage[key] += trace.get("usage", {}).get(key, 0)
        performance["successful_batches"] = sum(row["correct"] for row in performance["batches"])
        performance["estimated_api_cost_usd"] = str(sum(prices)) if len(prices) == len(predictions) else None
        performance["usage"] = usage
        performance["report"] = "eval/"+performance_path
        if "v9-linux" in performance_path:
            performance["execution_environment"] = linux_environment
    if not extraction or not methods:
        raise RuntimeError("Required real-run reports are missing")
    final = {"created_at": datetime.now(timezone.utc).isoformat(), "design": "post_tuning_synthetic_regression_not_blind", "team": team["team_name"], "members": team["members"],
             "model": extraction["model"], "prompt_versions": extraction["prompt_versions"], "schema_versions": extraction["schema_versions"],
             "extraction": {**extraction["summary"], "by_split": extraction["by_split"], "by_modality": extraction["by_modality"], "median_offer_seconds": extraction["median_offer_seconds"], "p95_offer_seconds": extraction["p95_offer_seconds"], "api_cost_estimate_usd": extraction["estimated_api_cost_usd"], "usage": extraction["usage"], "report": "eval/"+extraction_path, "execution": extraction["execution"], "duration_seconds": extraction["duration_seconds"], "hardware": extraction["hardware"]},
             "method_comparison": {"summary": methods["summary"], "one_prompt_median_seconds": methods["one_prompt_median_seconds"], "one_prompt_api_cost_estimate_usd": methods["one_prompt_estimated_api_cost_usd"], "report": "eval/"+methods_path, "baseline_reused": methods.get("execution") == "score_saved_baselines"},
             "normalizer_v7_targeted": {"status": "completed" if normalizer else "not_run", "summary": normalizer.get("summary") if normalizer else None, "report": "eval/results/normalizer-v7-targeted/report-all.json", "reason": "A saved-output audit found source-anchor ID collisions when one quote held two installments. Typed semantic identities and exact duplicate deduplication fix the review binding; this targeted run is preserved separately from the current full-corpus rerun."},
             "live_pdf_demo": {"status": "completed" if demo else "not_run", "passed": demo.get("passed") if demo else None, "cases": {key: {"passed": value["passed"], "status": value.get("analysis", {}).get("status"), "unique_winner": value.get("analysis", {}).get("unique_winner")} for key, value in demo["cases"].items()} if demo else {}, "report": "eval/"+demo_path},
             "production_length_ids_pdf_probe": {"status": "completed" if uuid_probe else "not_run", "passed": uuid_probe.get("passed") if uuid_probe else None, "report": "eval/"+uuid_path, "human_approval": False, "source_relationship_fixture_confirmed": uuid_probe.get("source_relationship_confirmed") if uuid_probe else None},
             "performance_three_by_five_pages": performance or {"status": "running", "report": "eval/results/performance-v6/report.json"},
             "prior_windows_performance": windows_performance,
             "human_study": {"status": "not_conducted", "participants": 0, "time_saving_claim": None, "protocol": "eval/STUDY_PROTOCOL.md"},
             "second_human_annotation_review": "pending",
             "limitations": ["24 synthetic cases / 48 offers; cases share prose templates and do not establish industry generalization.", "Frozen split failures informed changes. Final numbers are regression results, not a blind benchmark.", "No independent second human annotation review or organizer study has occurred.", "One-prompt and application both matched expected common-winner sets in all 24 cases; the one baseline mismatch is a conflict status classification, not an incorrect vendor choice.", "Exact quotation validation proves the quoted span exists, not that every interpretation is entailed by it.", "API costs are provider-token estimates at configured dated rates; OCR/CPU, hosting and storage costs are not measured.", "Per-offer p95 is not the full three-five-page-case target. Small repeated performance samples do not certify production p95."],
             "prior_runs": ["eval/results/evaluation-v1/report-development.json", "eval/results/evaluation-v2/report-frozen.json", "eval/results/evaluation-v3/report-development.json", "eval/results/evaluation-v4/report-all.json", "eval/results/evaluation-v6/report-all.json", "eval/results/evaluation-v8-linux/report-all.json", "eval/results/live-demo-v5/report.json", "eval/results/live-demo-v6/report.json", "eval/results/live-demo-v8-linux/report.json", "eval/results/performance-v6/report.json", "eval/results/performance-v8-linux/report.json", "eval/results/live-uuid-v8-linux.json", "eval/results/live-uuid-v8-linux-unconfirmed.json"]}
    output = ROOT/"reports"
    output.mkdir(exist_ok=True)
    (output/"final-summary.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = final["extraction"]
    lines = ["# Rzeczywiste wyniki ewaluacji", "", team["team_name"]+" | "+", ".join(team["members"])+" | 3 października 2026", "", "**To regresja na syntetycznych danych po dostrajaniu, nie ślepy benchmark ani badanie z organizatorami.**", "",
             f"Ekstrakcja Gemini 3.8 Flash: **{summary['correct_fields']}/{summary['critical_fields']} poprawnych krytycznych pól** w 24 zestawach / {summary['offers']} ofertach. Pominięcia: {summary['omissions']}; błędy providera/parsera: {summary['provider_or_parser_errors']}; kolizje identyfikatorów faktów: {summary.get('duplicate_normalized_fact_ids')}; niepoprawne odwołania do faktów: {summary.get('invalid_evidence_references')}. {summary['evidence_count']} cytatów wskazuje istniejące fragmenty źródeł. Poprawność interpretacji nadal wymaga przeglądu człowieka.", "",
             "| Próba automatyczna | Dokładny stan i wspólny zbiór zwycięzców | Zgodny zbiór zwycięzców |", "| --- | ---: | ---: |"]
    for key, label in (("one_prompt", "Jedno polecenie do tego samego modelu"), ("extraction_plus_engine", "Ekstrakcja i silnik"), ("annotation_replay_engine", "Silnik z autorskimi adnotacjami")):
        value = methods["summary"][key]
        lines.append(f"| {label} | {value['correct']}/{value['cases']} | {value.get('matching_winner_sets', 'pending')}/{value['cases']} |")
    lines.extend(["", "Różnica dotyczy klasyfikacji nierozstrzygniętego konfliktu aneksu jako `needs_clarification` zamiast `incomplete`. Baseline także nie wskazał wtedy bezwarunkowego zwycięzcy. Ten wynik nie dowodzi lepszych wyborów dostawcy ani oszczędności czasu użytkownika.", "",
                  f"Czas jednej oferty, wraz z parsowaniem: mediana {summary['median_offer_seconds']:.3f} s, obserwowane p95 {summary['p95_offer_seconds']:.3f} s. Koszt tokenów 48 ekstrakcji: szacowane {summary['api_cost_estimate_usd']} USD. Baseline: {methods['one_prompt_estimated_api_cost_usd']} USD dla 24 porównań. To nie jest koszt pełnego hostowanego produktu.", ""])
    if normalizer:
        value = normalizer["summary"]
        lines.extend([f"Audyt wyników v6 wykrył kolizje identyfikatorów faktów, gdy jeden cytat obejmował dwie różne raty. Poprawka v7 uwzględnia wartość i warunki faktu oraz scala tylko identyczne duplikaty. Osobna rzeczywista regresja rat, pakietów i aneksu: {value['correct_fields']}/{value['critical_fields']} pól; kolizje ID: {value.get('duplicate_normalized_fact_ids')}. Aktualny pełny wynik powyżej pochodzi z `{extraction_path}` i podaje rzeczywistą wersję promptu w JSON.", ""])
    if uuid_probe:
        lines.extend([f"Próba A + aneks z identyfikatorami UUID: zaliczenie {uuid_probe['passed']}. Adapter używa krótkich lokalnych aliasów źródeł i przywraca identyfikatory przed walidacją cytatów. To świeży odczyt PDF i wywołanie modelu, osobne od weryfikacji całej aplikacji.", ""])
        if "v9" in uuid_path:
            lines.extend(["Wersja v8 w osobnej próbie UUID zwracała dziedzinę bez odwołań do faktów i oznaczała zamknięte interpretacje jako niepełne. Silnik zatrzymał werdykt. Schemat v5 wymaga źródeł dla skończonej dziedziny, a prompt v9 oddziela kompletność opisanych interpretacji od przyszłych odpowiedzi dostawcy. Wynik v9 pochodzi z nowego wywołania, a wcześniejsze próby zachowano.", ""])
    if demo:
        lines.extend(["## Nowa inferencja z PDF i obie odpowiedzi", "", f"Zaliczone: {sum(value['passed'] for value in demo['cases'].values())}/{len(demo['cases'])}. Wynik w [raporcie PDF demo](../{demo_path}).", ""])
        for name, value in demo["cases"].items():
            result = value.get("analysis", {})
            lines.append(f"- {name}: {result.get('status', 'błąd ekstrakcji')}, wybór {result.get('unique_winner') or 'nierozstrzygnięty'}, zaliczenie {value['passed']}.")
    else:
        lines.extend(["Pomiar finalnego demo PDF jest w toku. Nie jest jeszcze wynikiem zaliczonym.", ""])
    if performance:
        lines.extend(["", "## Trzy oferty po pięć stron", "", f"n={performance['sample_size']} pełnych powtórzeń, współbieżność 2, bez cache aplikacji. Mediana {performance['median_seconds']:.3f} s; obserwowane p95 metodą najbliższej rangi {performance['observed_p95_nearest_rank_seconds']:.3f} s. Cel 60 s osiągnięty w tej próbie: {performance['observed_target_60_seconds_met']}.", "", "Przy n=5 p95 jest największą zaobserwowaną wartością, a nie stabilnym oszacowaniem produkcyjnym. Pomiar obejmuje odczyt, AI, walidację źródeł i silnik; nie obejmuje HTTP, kolejki, zapisu, logowania ani interfejsu. Dokumenty są czystymi syntetycznymi PDF, około 1200 znaków na stronę. Stanowisko nie było odizolowane od innych obciążeń.", ""])
        if "v9-linux" in performance_path and linux_environment:
            lines.extend([f"Środowisko Linux/WSL2, kontener z limitem {linux_environment['cpu_limit']} CPU i {linux_environment['memory_gib_limit']} GiB RAM, potwierdzone przez Docker inspect po pomiarze. Koszt tokenów 15 wywołań: szacowane {performance['estimated_api_cost_usd']} USD. Kod v9 uruchomiono w izolowanym katalogu wewnątrz obrazu API; nie jest to pomiar ścieżki przez HTTP.", ""])
        if performance_path != "results/performance-v6/report.json" and windows_performance:
            lines.extend([f"Oddzielny wcześniejszy pomiar Windows: {sum(row['correct'] for row in windows_performance['batches'])}/{windows_performance['sample_size']} poprawnych powtórzeń, mediana {windows_performance['median_seconds']:.3f} s, maksimum {windows_performance['max_seconds']:.3f} s. Zawiera dwa timeouty parsera podczas dużego obciążenia pamięci hosta. Zachowany bez zmian w [raporcie Windows](../results/performance-v6/report.json). Wynik Linux nie usuwa tej zaobserwowanej awarii.", ""])
    else:
        lines.extend(["", "Pomiar trzech pięciostronicowych ofert jest w toku. Czas jednej krótkiej oferty nie zastępuje tego pomiaru.", ""])
    lines.extend(["## Ograniczenia i niewykonane badania", "", "Dane i adnotacje powstały z pomocą AI, bez drugiej niezależnej weryfikacji człowieka. Odrębne nazwy rodzin dokumentów nie eliminują współdzielenia szablonów tekstu. Błędy wcześniejszego zbioru frozen wpłynęły na poprawki; wyników finalnych nie można przedstawiać jako ślepej oceny.", "", "Nie przeprowadzono badania z pięcioma organizatorami ani ręcznego porównania arkuszowego. Nie ma dowodu oszczędności 25%. Gotowy [protokół badania](../STUDY_PROTOCOL.md) i pusty arkusz obserwacji pozostają do przeprowadzenia z uczestnikami. Powtórzenie adnotacji przez silnik jest ablacją techniczną, nie pracą człowieka.", "", f"Pełne wyniki: [ekstrakcja](../{extraction_path}), [porównanie metod](../{methods_path}), [podsumowanie JSON](final-summary.json). Starsze przebiegi i wykryte błędy zachowano w results."])
    (output/"final-summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output/"final-summary.json"), "pdf_demo": final["live_pdf_demo"]["status"], "performance_ready": bool(performance)}))


if __name__ == "__main__":
    main()
