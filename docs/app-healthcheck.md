# 無料プランの休止対策

GitHub Actions が約3日ごと（毎月2・5・8・11・14・17・20・23・26・29日の日本時間09:23）に
公開アプリを新しいブラウザセッションで開き、Supabase読込の成功表示まで確認します。
単なるHTTP応答の確認ではなく、アプリ経由でデータベースへの読込を発生させます。
Streamlitの休止画面が出た場合は起動ボタンを押します。
月末をまたぐ間隔だけは2〜4日になります。存在しない日付は実行されません。
設定の反映時にも初回の動作確認を1回行います。

- 物件の追加・編集・削除・JSON復元は行いません。
- Supabaseの接続キーをGitHubへ登録する必要はありません。
- 物件内容、画面画像、ブラウザトレースをログや成果物として保存しません。
- 読込確認に失敗した場合は新しいセッションで最大3回試し、失敗として記録します。
- パソコンやCodexを起動しておく必要はありません。
- 公開リポジトリの標準GitHubホストランナーを使うため無料です。

GitHubは公開リポジトリに60日間活動がないと定期実行を無効にします。
その対策として、最後のコミットから30日経過し、読込確認に成功したときだけ
`.github/last-healthcheck.txt` に確認日を記録します。
この処理に限ってリポジトリへの書込権限を使い、物件データとアプリ本体は変更しません。

## 確認・停止

リポジトリの Actions → App health check で実行結果を確認できます。
Run workflow で手動確認、Disable workflow で定期実行を停止できます。
失敗通知はGitHubの個人通知設定に従います。

これは無料サービスの停止しにくさを改善する対策で、無停止の保証ではありません。
既にSupabaseが停止している場合は管理画面でResumeが必要です。
GitHubの実行遅延・障害、アプリ画面やURLの変更、非公開化、権限変更によって
確認に失敗することがあります。

参考:
- https://supabase.com/docs/guides/platform/free-project-pausing
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
- https://docs.github.com/en/actions/concepts/billing-and-usage
