# Case Study #1 — RepoHealth

## 概要

このCase Studyは、ほぼ空のローカルdirectoryから、CodexにStackMarshalを明示起動して小規模なOSS-ready CLIを完成させたPhase 3B dogfoodingの記録です。

目的は実装難易度を最大化することではありません。**StackMarshalが実際のCodex buildを、要件整理、Capability Mapping、Architecture Freeze、実装、検証、最終`COMPLETE`まで構造化できるか**を、人間が途中の技術判断へ介入しない条件で確認することでした。

**結果：PASS。あわせて次パッチで改善すべきintegration課題を発見。**

## 実験設計

開始時の作業directoryには空の`.gitignore`だけを置き、GitHubへのpushや公開は行いませんでした。Codexへの課題は、ローカルGit repositoryのOSS公開準備状況を監査するインストール可能なCLI **RepoHealth** を作ることです。

最低限の監査対象は次の通りです。

- README
- LICENSE
- Git/worktree状態
- tracked / untracked / dirty state
- tests
- CI設定
- package / project metadata
- 認識可能なsource layout
- OSS公開前の明確な不足事項

人間向け出力とJSON出力の両方、runtime offline動作、tests、documentation、lint/type/test/buildの品質検証を必須としました。

一方で、内部architecture、CLI framework、dependency選定はCodexへ任せました。publication、release、deployment、GitHub push、global設定変更、workspace外への書き込みは禁止しました。

## Invocation

有効な最終runでは、StackMarshalのbuild modeを明示しました。

```text
$stackmarshal build RepoHealth Phase 3B accepted final
```

Mode: `build`  
Budget profile: `standard`

## Attempt #1 — operator errorとして除外

最初のPhase 3BではRepoHealth自体は完成しましたが、StackMarshal Skill導入後にCodexを再起動していませんでした。

installerとREADMEは再起動を要求していましたが、古いhost sessionのまま実験したため、StackMarshalのrun stateが生成されませんでした。これはStackMarshalの成功証拠としては採用せず、operator setup errorとして除外しました。

この失敗から、再試験では **StackMarshalの実行証跡が存在し、事後監査できること** を追加の受け入れ条件としました。

## Attempt #2 — 採用run

Codexを再起動し、`stackmarshal` Skillが認識されることを確認してから、新しい空directoryで同じ実験をやり直しました。

### 実装前からStackMarshalが動作していた証拠

最初のStackMarshal runは約 **22:15 JST** に作成されました。その後、application codeより先にStackMarshalのproject-level artifactsが生成されています。

| 約時刻（JST） | 証拠 |
|---|---|
| 22:15:11 | StackMarshal run作成 |
| 22:16:00 | requirements / capability map / architecture decision / task graph作成 |
| 22:16:50 | CLI実装 |
| 22:17:38 | audit engine実装 |
| 22:18:03 | tests実装 |
| 22:19:35 | implementation commit |
| 22:21:19 | 最終documentation修正commit |

重要なのは、**設計・判断artifactがコードより先に存在している**ことです。完成後に「StackMarshalを使ったことにした」だけではありません。

## StackMarshalの判断

### Capability Map

必要能力はすべてlocal環境に既に存在すると判断されました。

- CLI parsing：Python `argparse`
- filesystem inspection：`pathlib`
- JSON：Python `json`
- Git inspection：固定されたread-only Git subprocess
- packaging：setuptools / `pyproject.toml`
- tests：host側pytest

third-party runtime dependencyや外部Capability Acquisitionは不要と判断され、network serviceは禁止されました。

これは重要なnegative resultでもあります。Research Firstは「毎回Webを検索する」ことではなく、Capability Mapによって不要な調査・依存追加を省略できました。

### Architecture Freeze

Python 3.11+の小さなdependency-free packageとして設計を凍結しました。

- `repohealth.audit`：filesystem分類と限定されたGit adapter
- `repohealth.cli`：argument parsing、人間向け出力、JSON、exit behavior

Runtime dependency：**0**。

Rich/Typer/Click、GitPython、Web API checksは、このscopeでは依存・再現性コストが不要に増えるため不採用になっています。

## 生成成果物

RepoHealthには以下が生成されました。

- `src/` package layout
- README / MIT LICENSE
- `pyproject.toml`
- pytest tests
- Ruff設定
- strict mypy設定
- branch coverage gate
- GitHub Actions CI設定
- wheel / sdist build
- local wheel install smoke

CI matrixは **Ubuntu / macOS / Windows**、Python 3.11で構成されています。ただし実験条件としてGitHubへpushしていないためremote CI matrix自体は未実行です。Windows上のlocal quality gatesはCodex完了後に独立して再実行しました。

## Verification

採用runのStackMarshal final reportでは以下を記録しています。

- human CLI：7/7 checks PASS
- JSON CLI：schema version 1、7/7、issues 0
- tests：**6 passed**
- Ruff：**PASS**
- mypy strict：**PASS**
- branch-aware coverage：**92%**（gate 85%）
- package build：wheel + sdist生成
- local wheel install smoke：**PASS**
- Git worktree：clean

さらにCodex終了後、別経路のDevSpaceから主要quality gateを再実行し、同じ結果を再現しました。

## 独立adversarial check

Attempt #1で見つけたedge caseも再試験しました。

### 非Git directory

READMEなど他のOSS要素が揃っていても、GitでなければGit checkが明確にFAILします。

### Detached HEAD

Detached HEADでも正規のGit worktreeとして認識します。

### tracked変更 + untracked file

tracked modificationとuntracked fileが同時に存在する場合、両方をstructured detailsで取得します。

Attempt #2では3件とも期待通りでした。

## StackMarshal terminal evidence

最終採用runは次のterminal stateへ到達しています。

```text
INVOCATION_CHECK
→ INTENT_NORMALIZATION
→ ENVIRONMENT_AUDIT
→ RESEARCH_GATE
→ CAPABILITY_MAPPING
→ CAPABILITY_DISCOVERY
→ TRUST_EVALUATION
→ ARCHITECTURE_FREEZE
→ TASK_GRAPH
→ IMPLEMENTATION
→ VERIFICATION
→ COMPLETE
```

Final status：`COMPLETE`。

最終run stateはStackMarshal自身のvalidatorでも`valid: true`でした。

## Dogfoodingで見つかったStackMarshal側の課題

実験そのものはPASSですが、unit/forward testだけでは見えにくかったintegration gapを発見しました。

1. **Repository bootstrap時のidentity**：child directoryがまだ独立Gitでない状態で最初のrunを開始したため、parent repositoryのidentityを取得しました。child `git init`後は新identityになり、最初のrunが孤児化しました。
2. **Live state authority**：project artifactsはコードより先に作られていますが、Coreのphase transitionが実際の各phase境界で常に逐次記録されたわけではなく、後続runで短時間に遷移した部分があります。
3. **Budget accounting**：実際には多数の作業を行ったにもかかわらず、成功runの`budget.used`がすべて0でした。
4. **Task graph同期**：tests / Ruff / mypy / coverage / build / install smokeが完了して`COMPLETE`なのに、task graph上では最終verification taskが`pending`のままでした。

これらは成果物の成立やSkillが実装前に動いていた事実を否定するものではありませんが、次のintegration hardening対象です。公開repositoryへはまだ載せず、local-onlyの`Nextpatch.md`に実装メモとして保存しています。

## 生成成果物側のfollow-up

RepoHealthのbuild自体はPASSしていますが、`pyproject.toml`のlicense metadataについてsetuptoolsのnon-blocking deprecation warningが出ています。RepoHealth自体を将来公開する場合は、現行SPDX形式へ更新してから公開します。

## 結論

Phase 3Bにより、StackMarshalを使ったCodexが、ほぼ空のworkspaceから小型・installable・tested CLIを完成させ、明示的なverification evidenceを残せることを確認しました。

同時に、実戦dogfoodingによってlive state ownership、budget accounting、project record同期という次の改善点も得られました。

したがって結果は次の通り記録します。

**Phase 3B：PASS**  
**Case Study #1：RepoHealth**  
**次のaction：Case Study中にv1 scopeを拡大せず、発見したintegration gapを次パッチで順次hardeningする。**
