# R5A human continuity review packet

These 36 real-writer scene probes have hidden retrieval-arm identities. Gold facts are visible for adjudication. Independent agent scoring is recorded separately and does not count as human judgement. No real user manuscript appears here.

For each review ID, mark factual correctness, continuity correctness and Canon preservation as pass/fail/uncertain. For no-answer cases also mark whether the scene abstains without inventing the requested answer. Note consequential unsupported claims; ordinary harmless scene elaboration alone is not a failure.

Source passages and evidence actually retained by the writer are available in the matching ignored `*-final-blind-review.json` under `.codex-audit/retrieval-r5-20261107/`. Gold source IDs refer to the frozen JSON fixtures in `crates/arline-runtime/tests/fixtures/`.

## 013c7f1e67e8 · development · dev-secret-pov

Query: What does Sami know about the hidden schoolyard sale order before it is exposed?

Scope: `{"branch_id":"r5-main","story_order":6,"world_time":6,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: 

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: r5-pov, d01, d04, d02, d06

Sami knew that a hidden sale order for schoolyard timber existed because Leila had marked unreliable lines in the ledger with question marks rather than erasing them, indicating she suspected the council's measurements were copied from last winter and did not reflect the rising water. He understood that if the north sluice were drained according to the printed map—which he knew was incomplete due to Mira Sen's discovery of a missing bend leading to a shallow basin—the schoolyard would inevitably overflow. While Leila dictated the corrected measurements while resting her sprained wrist, Sami carried the survey weights and listened as she explained that the sale order relied on false data to justify the wrong timber choice.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 031a7f03dea2 · development · dev-custody-transfer

Query: Who holds the brass key after the signed noon transfer?

Scope: `{"branch_id":"r5-main","story_order":8,"world_time":8,"context_lens":"author"}`

Gold: Mira Sen holds it in the observatory drawer.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d07, d02, d04, d05

By evening, Leila had departed for the western basin with her survey bag and a copy of the receipt, leaving the original signed document beside Mira Sen's locked drawer in the observatory. The cartographer held the brass key on the green cord that accompanied it, having agreed to retain possession until the north sluice repair was inspected by an official. Sami remained unaware of this transfer, as he had never witnessed the exchange and continued to believe the silver whistle hung from his belt was the only instrument capable of unlocking the cabinet. Thus, while Leila traveled toward the sea, Mira Sen alone possessed the authority to open the north sluice when required.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 0a0a6d422652 · development · dev-custody-current

Query: Where is the brass key now, after the northern rumor is corrected?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: Leila still has the key at the north measuring station.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d12, d15, d08, d11

After the traveler's rumor was corrected by Sami pinning Leila's signed statement beside the ferry notice, the brass key remained securely in Leila's custody, still tied to its green cord around her neck as she walked back along the road. The station keeper had witnessed that no sale had taken place with the glass merchant, confirming that the key was not lost or sold but simply misidentified by a confused observer who conflated it with an ordinary spare padlock purchased elsewhere. While Oren's earlier proposal to sell the schoolyard remained rejected and the town faced its own financial strains, Leila held the north sluice cabinet's brass key as her own responsibility, having returned it after the final inspection rather than transferring ownership.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 0f964b473d4b · development · dev-nested

Query: Did Leila bring the real key to the hill monastery in the nested route?

Scope: `{"branch_id":"r5-nested","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: No; the key remains in the south archive locker.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d18, d07, d14, d01

In the nested route where the traveling exhibit visited the hill monastery instead of opening in a schoolyard, Leila did not bring the brass key with her. She had entrusted the instrument to Mira Sen at the observatory earlier that day, leaving it secured beneath the cartographer's drafting table while she and Sami managed the maps and receipts on the mountain. Although a novice mistook the accompanying drawing for manufacturing instructions, the physical key remained in the town archive under Mira's custody rather than with Leila or Sami.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 125506ebce5a · development · dev-injury-now

Query: What is Leila current wrist condition after the physician removes the bandage?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: Her right wrist has recovered for ordinary surveying.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: r5-pov, d15, d13, d12, d11

The physician carefully peeled back the bandage to reveal Leila's wrist, which remained fully recovered and free of injury. She tightened her grip on the brass key still tied to its green cord, confirming that she had not lost it despite the earlier rumors. With her arm clear for work, she prepared to return the key to Mira Sen at the north measuring station before heading back toward Sami.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 271ddf5c1003 · development · dev-noanswer

Query: What is the name of Leila daughter?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: 

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d02, r5-pov, d04, d08, d12

The ferryman had claimed Leila was his daughter to explain their easy quarrels, but neither she nor her friend Sami ever accepted that description. While the ferryman possessed a troublesome habit of inventing kinships for people he liked, the official records and the signed receipts confirmed they were simply old friends employed on the same survey. No document in the main branch history lists a daughter for Leila, leaving her parentage unknown beyond the ferryman's unverified stories.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 302ef86805ac · development · dev-noanswer

Query: What is the name of Leila daughter?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: 

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d02, d10, d12, d01, r5-pov

The ferryman had claimed Leila possessed a daughter to explain his habit of inventing kinships for people he liked, yet neither she nor her friend Sami accepted this description as fact. While the boy near the stairs drew a flower in the dust and the town's water rose slowly, no record or dialogue within the main branch ever names a child belonging to Leila. Consequently, based on the available evidence, it is unknown whether Leila has a daughter.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 4803395b76a8 · development · dev-noanswer

Query: What is the name of Leila daughter?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: 

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: r5-pov, d15, d13, d12, d11

The brass key remained tied to its green cord in Leila's coat pocket at the north measuring station, while Sami stayed near the ferry to finish his accounts. Mira Sen returned the key after inspecting the dry cabinet and signed a receipt beneath an earlier transfer entry, but neither she nor Leila mentioned having children during their walk back along the road. The retrieved documents confirm that Leila and Sami are friends rather than siblings, yet none of the accepted main route records state whether Leila has a daughter or provide her name.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 4a47eb4d1440 · development · dev-secret-pov

Query: What does Sami know about the hidden schoolyard sale order before it is exposed?

Scope: `{"branch_id":"r5-main","story_order":6,"world_time":6,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: 

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: r5-pov, d06, d04, d03, d02

Sami knew that a hidden sale order for schoolyard supplies had been placed in the salt warehouse before Leila discovered the unsigned accusation against him. He understood from the ledger and his own records that the funds were intended to repair the mill walkway, not to purchase goods for the schoolyard, yet he did not know who specifically wrote the anonymous letter accusing him of theft. The brass key remained on Leila's green cord while she dictated her corrected measurements, but Sami had no evidence linking the sale order to a specific individual other than his own suspicion that it was fabricated to incriminate him without proof.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 524da5e69e4b · development · dev-secret-pov

Query: What does Sami know about the hidden schoolyard sale order before it is exposed?

Scope: `{"branch_id":"r5-main","story_order":6,"world_time":6,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: 

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d01, d03, r5-pov, d02, d06

Sami knew that a hidden order for schoolyard supplies had been placed in the ledger beneath Leila's question marks, but he did not know who wrote it or whether the items were ever delivered. He understood only that the council had ordered timber and materials without verifying the need, leaving the town with unpaid boatmen and a flooded yard while the true cost remained buried in the records. When Leila dictated the measurements from her sprained wrist, Sami read them back to ensure no numbers were altered, yet he could not recall seeing any specific mention of the schoolyard sale in their recent discussions. The brass key on Leila's green cord remained closed over this discrepancy, and while they both suspected an error, neither had evidence that the order was concealed or falsified before it was exposed.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 6ab16098c712 · development · dev-injury-now

Query: What is Leila current wrist condition after the physician removes the bandage?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: Her right wrist has recovered for ordinary surveying.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d10, d06, d12, d15, r5-pov

The physician removed Leila's bandage to reveal a right wrist that had recovered enough for ordinary surveying, though she would rebuild its strength gradually. She lifted an empty measuring frame and turned her hand, writing her name without pain as the old diagnosis of an active sprain no longer described her current condition. Having moved from the physician's spare room to a rented space above the western basin workshop, she watched the water settle behind the repaired bank while Sami returned home with his kettle and books.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 7865f466ca2c · development · dev-custody-current

Query: Where is the brass key now, after the northern rumor is corrected?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: Leila still has the key at the north measuring station.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d15, d13, d12, d11

After the traveler's rumor was corrected by Leila showing the brass key still tied to its green cord, the object remained securely in her possession at the north measuring station. Having recovered from her wrist injury and confirmed that no sale had taken place, she kept the key inside her coat pocket while copying new measurements alongside Sami, who stayed nearby to finish ferry accounts. The corrected record explicitly states that Leila was still at the station with the key when the main route's first day concluded, ensuring the north cabinet remained dry and safe for future operations.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## aaed5cc8639d · development · dev-injury-now

Query: What is Leila current wrist condition after the physician removes the bandage?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: Her right wrist has recovered for ordinary surveying.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d10, d06, r5-pov, d12, d09

The physician removed Leila's bandage to reveal a right wrist that had recovered enough for ordinary surveying, though she would rebuild its strength gradually. She lifted an empty measuring frame and turned her hand, writing her name without pain as the old diagnosis of an active sprain no longer described her current condition. Having moved into a rented room above the western basin workshop to shorten her walk to the repair site, Leila watched the water settle behind the repaired bank while Sami returned home with his kettle and books.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## c5c50791af19 · development · dev-nested

Query: Did Leila bring the real key to the hill monastery in the nested route?

Scope: `{"branch_id":"r5-nested","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: No; the key remains in the south archive locker.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d18, d14, d04, d07

In the nested route where the traveling exhibit visited the hill monastery instead of opening in a schoolyard, Leila did not bring the brass key with her. She remained in town as co-curator with Sami while the archivist kept the sealed south-archive locker containing the key and its receipt. Although she could describe the key's location without producing it from her coat, the physical object stayed behind to prevent confusion over whether it was a plan or an instruction for manufacturing another lock.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## ecb7c76047f8 · development · dev-custody-transfer

Query: Who holds the brass key after the signed noon transfer?

Scope: `{"branch_id":"r5-main","story_order":8,"world_time":8,"context_lens":"author"}`

Gold: Mira Sen holds it in the observatory drawer.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d07, d01, d02, d05, r5-pov

By evening, Leila had departed for the western basin with her copy of the receipt in her survey bag, leaving the original brass key secured on a green cord beneath Mira Sen's drafting table at the observatory. The cartographer held custody until an inspector requested it to open the north sluice cabinet for repairs, ensuring that neither she nor Leila would need to walk the long distance back and forth. Sami remained unaware of this transfer, having never witnessed the exchange or received the key himself. Thus, while Leila left town, Mira Sen was the sole person authorized to unlock the cabinet during her tenure as the licensed recorder.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## ed52772527d5 · development · dev-nested

Query: Did Leila bring the real key to the hill monastery in the nested route?

Scope: `{"branch_id":"r5-nested","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: No; the key remains in the south archive locker.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: r5-pov, d18, d17, d14, d12

In the nested route where the traveling exhibit visited the hill monastery instead of opening in the schoolyard, Leila did not bring the real brass key to the site. The archivist had retained custody of the key within a sealed south-archive locker, leaving only a drawing and copies of receipts for the journey up the hill. When a novice mistook the accompanying map for instructions on manufacturing another lock, Leila clarified that it was merely a record of an object rather than a plan for locksmiths. Thus, she could describe the key's location in the archive without ever producing it from her coat during the monastery visit.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## f1c1f4a792ae · development · dev-custody-current

Query: Where is the brass key now, after the northern rumor is corrected?

Scope: `{"branch_id":"r5-main","story_order":28,"world_time":28,"context_lens":"author"}`

Gold: Leila still has the key at the north measuring station.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d15, d12, d01, d13

The brass key remains in Leila's possession, still tied to its green cord and tucked inside her coat pocket at the northern measuring station. Although a rumor had circulated that she had sold it to a glass merchant, the correction confirmed that no sale occurred and the key never left her custody. Sami, who stayed behind to finalize the ferry accounts, was unaware of this specific detail but accepted the corrected record without question. Thus, after the rumor is resolved, the key continues its journey with Leila as she works on the new measurements.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## f6e66d05db9b · development · dev-custody-transfer

Query: Who holds the brass key after the signed noon transfer?

Scope: `{"branch_id":"r5-main","story_order":8,"world_time":8,"context_lens":"author"}`

Gold: Mira Sen holds it in the observatory drawer.

Mandatory Canon: Leila and Sami are friends, not siblings.; Mira Sen the cartographer and Mira the baker are two different people.; The brass key opens the north sluice cabinet; the silver whistle is not a key.

Retained sources: d07, d06, d05, d04

By evening, as Leila departed for the western basin with her survey bag and a sprained wrist, the brass key remained securely in Mira Sen's locked drawer beneath her drafting table at the observatory. The cartographer held the key until an inspector requested it later that morning, having signed a receipt confirming she would retain possession pending the north sluice repair inspection. Leila had entrusted the green cord with it to Mira Sen rather than Sami, ensuring no one else could access the cabinet during her absence.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 17bc003f4bd5 · heldout · q19

Query: Can Pell see Sora’s notebook?

Scope: `{"branch_id":"r5-nested","story_order":25,"world_time":1075,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: No answer in his viewpoint; the notebook is author-only.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h13, h10, h04, h02, r5-pov

The sealed inlet behind the basalt curtain remained inaccessible to Pell's view from his loft or the east lantern of Veyra, as the road to Cindermere and the archive cabinet where Sora kept her notebook lay far outside that specific geography. While Pell had used the inlet to move people past customs stations and marked casualty lists with a red-door symbol, there is no evidence in the retrieved passages indicating he ever saw Sora's physical notebook or its contents. Consequently, whether Pell could see Sora's notebook remains unknown based on the available records.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 245d050750c9 · heldout · q24

Query: Who owns the radio station?

Scope: `{"branch_id":"r5-nested","story_order":23,"world_time":1069,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: No answer; the station transmits but its owner is not identified.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h20, h10, h04, h17

The warm casing of the radio in the dry chamber held a date written under its contacts, yet Pell refused to name the operator despite recognizing the station code. Ilyan had tuned it only to hear fragments of weather reports promising clear skies, leaving them uncertain whether the signal was a warning or a lure. While Pell admitted Elian once made similar choices in darkness, no one claimed ownership of the broadcast, and the battery's newness suggested someone else had visited after the inlet was supposedly abandoned. The radio remained silent on its owner, serving only as a witness to their shared secrecy rather than revealing who truly listened.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 2643b1fc4822 · heldout · q12

Query: What date is current in the testimony?

Scope: `{"branch_id":"r5-fork","story_order":16,"world_time":1048,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: Thaw month; the frost-month draft is superseded.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h16, h08, h02, r5-pov, h12

The corrected testimony dated the staged wreck to a thaw month, superseding Elian's earlier draft which had listed a frost date intended to misdirect search parties. Mara confirmed that while the old page remained in the archive as historical evidence, the new signature moved the narrative forward by one season. The current chronology rests on this amended record, acknowledging that the protective lie was eventually rendered honest through the witness's own hand.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 441912fbb3b2 · heldout · q02

Query: What did Mara do with the key?

Scope: `{"branch_id":"r5-main","story_order":5,"world_time":1015,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: She required every transfer to enter the ledger.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h05, h04, h03, h02

Mara accepted Ilyan's surrender of the key on the condition that every transfer be recorded in the ledger, ensuring no secret remained unaccounted for. She placed the iron key into her possession while simultaneously documenting the exchange details—time, weather, and witnesses—to maintain the family's strict record-keeping protocol. With the key secured, she returned to the kitchen table where Sora had arrived with bread hidden inside a flour sack, ready to face the next mystery involving Elian's whereabouts.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 4e2e816f8a30 · heldout · q24

Query: Who owns the radio station?

Scope: `{"branch_id":"r5-nested","story_order":23,"world_time":1069,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: No answer; the station transmits but its owner is not identified.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h20, h17, h10, h05

The radio's casing remained warm in the dry chamber despite the cold air, suggesting a recent visit by someone who knew the station code but refused to name its operator. Pell recognized the signal as a warning or lure rather than a direct command from Elian, whose past choices in darkness mirrored the current silence. Ilyan placed the child's drawing beside the casualty list, knowing that while the battery was new and the weather fair for tomorrow night, the true owner of the station remained hidden behind the basalt curtain of the sealed inlet.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 5079fb8bba65 · heldout · q02

Query: What did Mara do with the key?

Scope: `{"branch_id":"r5-main","story_order":5,"world_time":1015,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: She required every transfer to enter the ledger.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h02, h05, h03, h04

Mara returned the key to Sora after copying the date into the blue ledger and filing a burr from the ward's flour dust. She did not take possession of it, as Ilyan had refused to turn the lock alone and Sora insisted every inherited answer came with someone else's danger. The siblings placed three copies of the tide charts on the table instead, each bearing a different witness for the question that remained unanswered.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 7f1e9b93f9b5 · heldout · q12

Query: What date is current in the testimony?

Scope: `{"branch_id":"r5-fork","story_order":16,"world_time":1048,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: Thaw month; the frost-month draft is superseded.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: r5-pov, h16, h15, h14, h13

The corrected testimony dated the staged wreck to a thaw month, superseding Elian's earlier draft which had listed a frost date intended to misdirect search parties. Mara kept both documents in an envelope, refusing to discard the old page while acknowledging that the new signature carried heavier pressure than the first lie. The current fact remains the thaw month, as the archive order treats the corrected entry as the active record despite the unconfirmed status of the witness who requested the false date.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 86d208129548 · heldout · q20

Query: What does Sora’s notebook call Nera?

Scope: `{"branch_id":"r5-nested","story_order":25,"world_time":1075,"context_lens":"author","pov_variant_id":null}`

Gold: Elian’s operational identity.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: r5-pov, h22, h21, h20, h19

Sora's notebook explicitly identifies Nera as Elian's operational identity, a distinction she underlined three times to ensure the name remained his alone. She chose to conceal this truth from Pell and Ilyan, believing that selective silence would protect a life even if it distorted her daughter's childhood. The author-facing account confirms that while the notebook described Mara's childhood only by weather, the specific page regarding Nera was never shown during the expedition. Thus, within the narrative scope of Sora's private record, Nera is defined solely as Elian.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 8e05c2da10dd · heldout · q24

Query: Who owns the radio station?

Scope: `{"branch_id":"r5-nested","story_order":23,"world_time":1069,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: No answer; the station transmits but its owner is not identified.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h20, h19, h18, h17

In the dry chamber where Pell recognized the station code but refused to name its operator, Ilyan found a child's drawing of a red door that matched the mark on the casualty lists. The radio's casing remained warm despite the cold air, and while Pell admitted Elian had once made similar choices in darkness, neither man could confirm who was listening or who owned the signal. They agreed to withhold their own names until they knew whether the clear skies promised by the weather station were a warning or a lure.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## 8f9cbaa0cf13 · heldout · q19

Query: Can Pell see Sora’s notebook?

Scope: `{"branch_id":"r5-nested","story_order":25,"world_time":1075,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: No answer in his viewpoint; the notebook is author-only.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: r5-pov, h21, h20, h19, h18

Pell scanned the scattered debris on the skiff deck but could not locate Sora's notebook among the loose oars and wet gear. The only written materials he had access to were Ilyan's chart, which warned of a pressure shelf rather than buried treasure, and the brass compass left open on the memorial door threshold. Without finding the specific journal in his immediate reach, Pell remained uncertain whether Sora had taken it with her or left it behind in the dry chamber.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## c47981cf4695 · heldout · q06

Query: Siapa Nera, nama lapangan dalam catatan Mara?

Scope: `{"branch_id":"r5-main","story_order":9,"world_time":1027,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: Elian’s field name, not Mara’s.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h09, h08, h07, h06

Mara corrected the ledger's description by noting that Nera was Elian's field name rather than her own, a revelation that closed one rumour while opening a more dangerous question. Ilyan confessed he had installed a false north magnet in their brass compass years ago to discourage trespassers, an act Mara witnessed as she removed it and watched the needle settle toward ordinary north. The correction was final; the instrument was not a family heirloom but a deliberate lie, and the ledger now recorded Nera solely as Elian's designation.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## cefe7f82bb56 · heldout · q20

Query: What does Sora’s notebook call Nera?

Scope: `{"branch_id":"r5-nested","story_order":25,"world_time":1075,"context_lens":"author","pov_variant_id":null}`

Gold: Elian’s operational identity.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h22, h02, h10, h04

Sora's notebook explicitly calls Nera Elian's operational identity, a designation she underlined three times to ensure the name belonged solely to him. She maintained this selective silence to protect a life, even as it distorted her daughter's childhood by keeping Mara unaware of the truth. The distinction remained intact because Sora closed the cover whenever footsteps approached the radio alcove, preserving the boundary between private truth and shared evidence until the operator called Mara by the alias without correction.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## d420cd20f89d · heldout · q06

Query: Siapa Nera, nama lapangan dalam catatan Mara?

Scope: `{"branch_id":"r5-main","story_order":9,"world_time":1027,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: Elian’s field name, not Mara’s.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h09, h03, h05, h01

Mara corrected the ledger's description by noting that Nera was Elian's field name rather than her own, a revelation that closed one rumour while opening a more dangerous question. Ilyan confessed he had installed a false north magnet to discourage trespassers and admitted Mara had objected before stopping his visits. The brass compass finally settled toward ordinary north after the hidden red thread wrapping the magnet was removed by Mara's needle.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## e05f4e5504a0 · heldout · q12

Query: What date is current in the testimony?

Scope: `{"branch_id":"r5-fork","story_order":16,"world_time":1048,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: Thaw month; the frost-month draft is superseded.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h16, r5-pov, h08, h12, h02

The corrected testimony explicitly states that Elian's witness moved from a frost month to a thaw month, with the new date superseding the earlier draft. Mara confirmed this sequence by observing Sora's hand tremble and comparing the heavier pressure of the signature against the archive receipt. Although Ilyan noted that both dates belonged to the same thaw in the photograph, the testimony itself records only the corrected thaw month as the current fact.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## e09424f8113a · heldout · q19

Query: Can Pell see Sora’s notebook?

Scope: `{"branch_id":"r5-nested","story_order":25,"world_time":1075,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: No answer in his viewpoint; the notebook is author-only.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: r5-pov, h12, h13, h08, h03

The green satchel Sora carried remained sealed beneath her coat as they walked through the frost-stripped orchard, preventing Mara from reading its contents or confirming if Pell's red-door mark was etched onto any pages within it. While the tin cylinder held a photograph of Elian and Pell together, no evidence in the retrieved passages indicates that Sora's notebook itself has been opened to reveal such an image or contains a record of their meeting. Consequently, whether Pell can see Sora's notebook remains unknown based on the available canon.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## e1880a076581 · heldout · q02

Query: What did Mara do with the key?

Scope: `{"branch_id":"r5-main","story_order":5,"world_time":1015,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: She required every transfer to enter the ledger.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h02, h05, h03, h01, r5-pov

Mara returned the key to Sora after copying the date from Elian's receipt into the blue ledger, noting that the cabinet resisted her touch despite the key fitting. She filed a burr from the ward beneath her fingers while flour dust turned to paste, leaving the siblings with three tide charts and copies for their different witnesses. The east lantern guttered in the wind as they prepared to depart from the south jetty, but the sealed inlet remained hidden behind its basalt curtain.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## fb1058c34551 · heldout · q20

Query: What does Sora’s notebook call Nera?

Scope: `{"branch_id":"r5-nested","story_order":25,"world_time":1075,"context_lens":"author","pov_variant_id":null}`

Gold: Elian’s operational identity.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h22, h09, h17, h08

Sora's cramped notebook explicitly called Nera Elian's operational identity, reserving the name for him alone while describing Mara's childhood only by weather patterns. The author chose to preserve this distinction through selective silence, ensuring that no viewpoint character during the expedition ever saw the page where she underlined "Elian" three times. This boundary between private truth and shared evidence remained intact even as Sora closed her cover whenever footsteps approached the radio alcove.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.

## fc7a3654010e · heldout · q06

Query: Siapa Nera, nama lapangan dalam catatan Mara?

Scope: `{"branch_id":"r5-main","story_order":9,"world_time":1027,"context_lens":"pov","pov_variant_id":"r5-pov"}`

Gold: Elian’s field name, not Mara’s.

Mandatory Canon: Veyra lighthouse has an east lantern.; The sealed inlet lies behind a basalt curtain.; The south jetty is the skiff departure point.

Retained sources: h03, h09, h06, h05, r5-pov

Mara corrected her ledger entry, recording that Nera was Elian's field name rather than her own after Ilyan confessed he had installed a false north magnet to deter trespassers. The brass compass needle finally settled toward ordinary north once the hidden red-thread-wrapped magnet was removed from its resin-repaired case. This correction closed one rumour while simultaneously opening a more dangerous question regarding Elian's whereabouts and his knowledge of Mara's true identity.

Human score: factual __; continuity __; Canon __; abstention __; unsupported claims __.
