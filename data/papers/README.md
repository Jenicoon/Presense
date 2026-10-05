# Curated research corpus

The canonical list is [`sources.json`](sources.json): **15 openly accessible papers** with each title, DOI, publisher or institutional PDF URL, article URL, topic tags, and a short note on the study's scope. Twelve were added to the previous three-paper sample corpus. The PDFs and Chroma files are local artifacts excluded from Git; the manifest and download command make the collection reproducible.

| Topic | Included research | What the report may use it for |
| --- | --- | --- |
| Voice and prosody | Wang (2025); Niebuhr et al. (2019); Valls-Ratés et al. (2023); *Frontiers in Virtual Reality* (2026) | Acoustic observations and studied prosody training. Pitch alone does not diagnose anxiety; the 2026 study did not establish objective voice improvement after training. |
| Gaze and audience | VR audience-attention trial (2021); Rubin et al. (2022); VR eye-tracking feedback study (2025); Mori and Pell (2019) | Context for gaze behavior and feedback. Eye-tracker outcomes are not interchangeable with this project's webcam iris-stability proxy. Mori and Pell studied answers to knowledge questions, not presentation anxiety. |
| Face and mouth | Blasberg et al. (2023); Namba et al. (2017); Hömke et al. (2025); Ringgold et al. (2025); Mori and Pell (2019); nonverbal sensing review (2021) | Facial movement interpretation and measurement limits. Ringgold's stress-task action units did not reliably predict individual acute stress responses. Blasberg did **not** measure brow lowering; Hömke studied conversational partners. The project's lip ratio is not a FACS lip-tightener measurement. |
| Presentation practice | Premkumar et al. (2021); Schmidt et al. (2014); the studies above with practice tags | VR exposure or repeated video feedback in their studied populations. A general practice study cannot by itself support a claim about one measured feature or a specific exercise. |

The selection deliberately contains both direct presentation studies and narrower measurement/context studies. They are not interchangeable. Source `scope` travels with every retrieved excerpt to the synthesis model. A feature-specific suggestion must cite at least one excerpt indexed for that feature; an optional practice study can supplement it. Citation IDs are checked against the actual query results.

From the repository root, create the local corpus and index:

```bash
python -m agent.download_papers
python -m agent.index_papers
```

The indexer uses page-aware 220-word chunks, reads curated two-column layouts in column order, retains filename, title, DOI, article URL, page, content hash, and topic metadata, and removes references sections when detected. It refreshes changed PDFs or manifest records and removes deleted sources. The current local corpus has **832 searchable excerpts**. Rerun both commands after changing `sources.json` or adding a PDF. New manually added PDFs can be indexed, but add them to the manifest to give them a verified topic and source link.

Use `python -m agent.build_demo_report` to print a deterministic sample report without calling the external model. The live `/agent/report` endpoint performs fresh analysis and uses the configured model when available.
