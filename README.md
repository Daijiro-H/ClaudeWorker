# S&P500 RSI Notifier

S&P500(^GSPC)の日足終値からRSI(14)を計算し、毎日LINE公式アカウント(Messaging API)で通知するツールです。
RSIが70以上(買われすぎ)または30以下(売られすぎ)になった場合は、通知内にアクション検討のシグナルを表示します。

(LINE Notifyは2025年3月31日にサービス終了したため、後継のMessaging APIを使用しています。)

## 仕組み

- `scripts/check_sp500_rsi.py` が yfinance で S&P500 の直近の終値を取得し、Wilder方式のRSI(14)を計算します。
- 計算結果を LINE Messaging API の push message でメッセージとして送信します(毎日1回、平日)。
- GitHub Actions のスケジュール実行 (`.github/workflows/daily-rsi-check.yml`) により、平日22:30 UTC(米国市場のクローズ後)に自動実行されます。

## セットアップ

### 1. LINE公式アカウント(Messaging APIチャネル)の作成

1. [LINE Developers Console](https://developers.line.biz/console/) にログイン(お持ちのLINEアカウントでOK)
2. プロバイダーを作成(未作成の場合)し、「新規チャネル作成」から **Messaging API** チャネルを作成
3. 作成したチャネルの `Messaging API設定` タブで **チャネルアクセストークン(長期)** を発行
4. 同じくチャネルの `Messaging API設定` タブに表示されるQRコードから、通知を受け取りたいLINEアカウントでBotを友だち追加
5. `チャネル基本設定` タブ下部の「あなたのユーザーID」を確認(自分宛てにpushする場合のユーザーIDとして使用可能)

### 2. GitHub Secrets への登録

リポジトリの `Settings > Secrets and variables > Actions` で以下のSecretを登録してください。

| Secret名 | 内容 |
| --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` | 発行したチャネルアクセストークン(長期) |
| `LINE_USER_ID` | 通知を送りたいLINEアカウントのユーザーID |

### 3. 動作確認

`Actions` タブから `Daily S&P500 RSI Check` ワークフローを選択し、`Run workflow` で手動実行して通知が届くことを確認してください。

## ローカル実行

```bash
pip install -r requirements.txt
export LINE_CHANNEL_ACCESS_TOKEN=xxxxxxxx
export LINE_USER_ID=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
python scripts/check_sp500_rsi.py
```

## 通知の例

```
S&P500 RSIチェック
日付: 2026-08-04
終値: 5,432.10
RSI(14): 72.3
シグナル: 買われすぎ(RSI >= 70) -> 売りアクション検討
```

## カスタマイズ

- RSI期間やしきい値は `scripts/check_sp500_rsi.py` 冒頭の `RSI_PERIOD` / `OVERBOUGHT` / `OVERSOLD` で変更できます。
- 実行時刻は `.github/workflows/daily-rsi-check.yml` の `cron` を変更してください(UTC指定です)。

---

# PLTR $160 Notifier

Palantir(PLTR)の株価が **$160 に到達したか** を毎朝チェックして通知するツールです。
PLTRは$160より上で推移しているため、「下落して$160に到達したか」を判定します。

## 仕組み

- `scripts/check_pltr_price.py` が yfinance で PLTR の直近の日足を取得し、終値・高値・安値を確認します。
- 判定条件: **終値が$160以下**、または **その日の安値が$160を割り込んだ** 場合に「到達」とします(ザラ場で一時的に到達したケースも拾います)。
- GitHub Actions のスケジュール実行 (`.github/workflows/daily-pltr-check.yml`) により、毎日 23:00 UTC(= 翌朝 **8:00 JST**、米国市場のクローズ後)に自動実行されます。

## 通知経路

このツールは通知経路を2つ持ちます。**設定なしで動くのはGitHub Issueの方です。**

| 経路 | 送信タイミング | 必要な設定 |
| --- | --- | --- |
| **GitHub Issue** | $160に到達したときのみ | **不要**(`GITHUB_TOKEN` を自動使用) |
| LINE Messaging API | 毎日(到達・未到達どちらも) | `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` |

$160に到達するとリポジトリにIssueが自動作成され、GitHubからオーナー宛にメール通知が飛びます。
Secretsの登録は不要で、これがこのツールの主たるアラート経路です。

LINEのSecretsが未設定の場合、LINE送信は警告を出してスキップされるだけで、**ワークフローは失敗しません**。
GitHub Issueによる通知はそのまま機能します。

判定結果は到達・未到達にかかわらず、毎回 GitHub Actions の **ジョブサマリー** にも出力されます
(`Actions` タブの各実行結果ページで確認できます)。

## セットアップ

### 必須: 既定ブランチへのマージ

GitHub Actions のスケジュール実行(`on: schedule`)は **リポジトリの既定ブランチ上のワークフローしか起動しません**。
このブランチをマージするまで、毎朝の自動実行は始まりません。マージ前に動作を試す場合は
`Actions` タブから `Daily PLTR $160 Check` を選び、`Run workflow` で手動実行してください。

### 任意: LINE通知を有効にする

毎日LINEでも受け取りたい場合のみ、`Settings > Secrets and variables > Actions` に以下を登録してください
(S&P500 RSIツールと同じSecretsを共用します)。

| Secret名 | 内容 |
| --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` | チャネルアクセストークン(長期) |
| `LINE_USER_ID` | 通知を送りたいLINEアカウントのユーザーID |

## ローカル実行

```bash
pip install -r requirements.txt
python scripts/check_pltr_price.py
```

Secretsなしでも実行でき、判定結果が標準出力に表示されます。

## 通知の例

```
PLTR $160 チェック
日付: 2026-08-27
終値: 158.40
高値: 162.00 / 安値: 155.00
判定: 到達($160以下) -> アクション検討
```

## カスタマイズ

- しきい値は `scripts/check_pltr_price.py` 冒頭の `DEFAULT_THRESHOLD` で変更できます。
- 一時的な上書きは、`Run workflow` の `threshold` 入力(環境変数 `PLTR_THRESHOLD`)で行えます。
  高い値(例: `999`)を指定すると必ず「到達」と判定されるため、**通知が実際に届くかのテスト**に使えます。
- 銘柄は同じく `TICKER` で変更できます。
- 実行時刻は `.github/workflows/daily-pltr-check.yml` の `cron` を変更してください(UTC指定です。JSTから9時間引いた値になります)。
