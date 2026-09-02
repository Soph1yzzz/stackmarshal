# Case Study #2 — MandateMarshal v0.2 durable runtime / crash recovery

## 概要

MandateMarshal v0.2のdurable runtime / crash recovery実装でStackMarshalを実使用しました。Case Study #1のcontrolled Phase 3B dogfoodingとは異なり、これは別Sol sessionが実際のOSS開発タスクを進める中で得たfield-use記録です。

runはbuild mode / standard budgetで開始し、StackMarshal自身のcompletion gateとfinalization contractを通過してから`COMPLETE`へ到達しました。

報告されたrun metrics:

- research rounds: **1**
- tool calls: **72**
- mandatory tasks: **5**
- task attempts: **5**
- 各taskのattempt: **1**
- terminal state: **`COMPLETE`**

最も大きな製品上の結果は、長時間のAgent作業を暗黙的な「会話」ではなく、phase・task・budget・verification・finalizationが外部stateとして残る明示的なrunへ変換できたことです。

## 実使用で確認できた価値

### 実装中でもphase boundaryが有効だった

runは次のbounded workflowを通りました。

`RESEARCH -> ARCHITECTURE_FREEZE -> TASK_GRAPH -> IMPLEMENTATION -> VERIFICATION`

field reportでは、調査を永遠に続けることと、設計が固まる前に実装へ突入することを防ぎやすい点が特に評価されました。

### crash recovery開発とtask evidenceの相性が良かった

実装は5 taskへ分割され、全taskが1 attemptで完了しました。各taskをacceptance criteriaとevidence付きで閉じる方式は、実装途中で追加の境界条件が見つかりやすいcrash recovery開発でも、何を満たしたかを失わず進められる点で有効でした。

### completion gateが実際のverification freshness漏れを止めた

VERIFICATION後に追加のsource変更が入った状態で、再verificationせず`COMPLETE`へ進もうとしたところ、StackMarshalは次の理由でtransitionを拒否しました。

```text
missing_verified_workspace_fingerprint
```

最終workspaceに対してverificationをやり直すまでcompletionを主張できなかったため、このcase studyで最も強い結果です。completion gateは単なる記録ではなく、stale verification evidenceで`COMPLETE`になることを実際に防ぎました。

### finalization後のterminal recordが追跡しやすかった

final reportにはrun ID、mode、phase/status、budget usage、phase fingerprints、verification fingerprint、finalization hashes、terminal sealが集約されました。長いchat履歴から後で作業を復元するより、runとして何が起きたかを確認しやすいという評価でした。

## Field useで発見した問題

### 1. Terminal sealのGit porcelain parsingでdirty pathが壊れる

terminal seal内で`AGENTS.md`が`GENTS.md`として記録される事象が確認されました。

StackMarshal sourceを追跡すると、`state.py`の`_run_git()`が`git status --porcelain`出力へ汎用`.strip()`を適用し、その後terminal snapshot側が`entry[3:]`でpath部分を切り出していました。Git porcelainのleading whitespaceはstatus columnそのものなので、先に削るとpath列が1文字ずれます。

これは確認済みのStackMarshal実バグで、v1.1.3の修正対象です。

### 2. 複数のStackMarshal実行経路によるversion ambiguity

field reportでは、local環境の異なるlaunch pathから異なるStackMarshal versionが見える状態が確認されました。後続調査でも、managed launcher、別Pythonの`Scripts` launcher、installed package metadata、loaded Skillが同時に異なるversionを示し得る状態を再現しました。

元のfield reportでは、ある1.1.1実行経路で`task complete --evidence`が受理されなかったとも報告されました。ただし、公式v1.1.1 sourceと現在のmanaged v1.1.1 launcherを後から確認したところ、公式parserには`--evidence`が存在し、この「v1.1.1そのものに入力経路がない」という狭い主張は再現できませんでした。

そのため本Case Studyでは、確認済みの結論をより限定して、**stale / alternate execution pathを十分に識別できないversion provenance問題**として記録します。

v1.1.3の`doctor`は、invoked CLI、installed Skill、managed install state、PATH resolution、複数StackMarshal launcher candidate、非実行で得られるversion evidenceを表示します。doctor自身がPATH上の別launcherを片っ端から実行してversionを確認することはしません。

### 3. Windows予約device名でfingerprint診断が誤解を招く

workspaceにはignoredな0 byte artifact `NUL`が存在し、workspace fingerprintが通常の「entry changed during fingerprint」に近い診断で停止しました。`NUL`を削除するとverificationは正常化しました。

これは通常のファイル変更ではなくWindows固有の予約device名semanticsです。v1.1.3では`CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`をpath component単位で検出し、resolve/read前に原因を明示します。

ただしfingerprint対象から黙って除外はしません。terminal evidenceがworkspace contentを見落とす可能性があるため、fail-closedを維持します。

### 4. `init`が対象repoの`.gitignore`を変更する

現行`stackmarshal init`はStackMarshal run state用patternをproject `.gitignore`へ追加します。現在の設計としては意図的ですが、orchestrator bookkeepingだけでtarget repoをdirtyにしたくない運用が実使用で確認されました。

これはv1.1.4へ分離し、`.git/info/exclude`またはrepo外stateを利用するlocal / non-invasive init modeとして検討します。

### 5. `audit`はdelivery auditではなくenvironment inventory

現行`stackmarshal audit`はenvironmentとnative capability inventoryを生成します。field reportでは、changed files、mandatory task acceptance/evidence、verification freshness、unresolved failures、finalize readinessを横断する最終reviewを期待していました。

より広いdelivery reviewはv1.1.4へ分離します。既存environment auditは有用なので、暗黙に意味を変えるのではなくscopeを明示的に分離する方針です。

### 6. Human CLIとしては出力がverbose

phase transition時にfull run JSONが出るため、machine outputとしては強い一方、interactive terminalでは流量が多いという指摘がありました。compact human default + 明示的full JSON modeはv1.1.4へ分離します。

## v1.1.3への反映

Case Study #2からv1.1.3のruntime-trust hardening scopeを次の3点に固定します。

1. Git porcelain status columnを維持し、terminal dirty-path parsingを修正する。
2. `doctor`でlauncher / CLI / Skill / managed installのversion skewを検出・可視化する。
3. Windows予約device名をworkspace fingerprintで専用診断し、fail-closed evidence semanticsを維持する。

repo非侵襲init、delivery audit、compact CLI outputはv1.1.4へ分離し、v1.1.3をexecution/evidence trustの修正に限定します。

その後のpre-release security reviewで、このfield run由来ではない4件目のv1.1.3 trust issueも見つかりました。checkpointとacquisition receiptにはユーザー領域integrity認証がある一方、live runとcanonical task authorityには同等の保護がありませんでした。v1.1.3ではこの差も閉じています。field runが発見したと後付けしないため、この内容は後日談として分離して記録します。

## Evidence provenanceと留保

この文書はfield-use記録であり、MandateMarshal repositoryや生のStackMarshal run directoryがこのrepository内にarchiveされていると主張するものではありません。

run metricsとworkflow所感はMandateMarshal v0.2を実装したSol sessionの報告に基づきます。その後StackMarshal repository側でsourceを確認し、porcelain parsing bug、現行`audit`がenvironment inventoryであること、`init`が`.gitignore`を変更することを独立に確認しました。またlocal環境で複数versionのStackMarshal installation ambiguityも再現しました。

一方、公式v1.1.1に`task complete --evidence`が存在しないという狭い主張は後続確認で再現できなかったため、強い断定を残さず、確認できたversion/execution-path ambiguityのみを事実として記録しています。

この留保は意図的です。成功したgateだけでなく、実使用で何が分かり、どこまで再現できたかをそのまま残すことがCase Studyの目的です。
