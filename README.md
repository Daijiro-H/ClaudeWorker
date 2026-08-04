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
