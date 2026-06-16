param(
    [string]$OutDir = "",
    [string]$DateStamp = "",
    [int]$TopPreview = 100
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $OutDir) {
    $OutDir = Join-Path $ProjectRoot "exports\trading-mvp\universe"
}
if (-not $DateStamp) {
    $DateStamp = Get-Date -Format "yyyy-MM-dd"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$exchangeInfo = Invoke-RestMethod -Uri "https://api.binance.com/api/v3/exchangeInfo" -Method Get -TimeoutSec 30
$binanceAssets = @{}
foreach ($symbolInfo in $exchangeInfo.symbols) {
    if ($symbolInfo.status -eq "TRADING") {
        $binanceAssets[$symbolInfo.baseAsset.ToUpperInvariant()] = $true
        $binanceAssets[$symbolInfo.quoteAsset.ToUpperInvariant()] = $true
    }
}

$tickers = Invoke-RestMethod -Uri "https://api.coinpaprika.com/v1/tickers?quotes=USD" -Method Get -TimeoutSec 30
$ranked = $tickers | Where-Object { $null -ne $_.rank } | Sort-Object rank

$fullMissing = foreach ($coin in $ranked) {
    $symbol = ([string]$coin.symbol).Trim().ToUpperInvariant()
    if (-not $binanceAssets.ContainsKey($symbol)) {
        $marketCap = if ($coin.quotes -and $coin.quotes.USD -and $null -ne $coin.quotes.USD.market_cap) {
            [double]$coin.quotes.USD.market_cap
        } else {
            0.0
        }
        $price = if ($coin.quotes -and $coin.quotes.USD -and $null -ne $coin.quotes.USD.price) {
            [double]$coin.quotes.USD.price
        } else {
            0.0
        }
        [PSCustomObject]@{
            rank = [int]$coin.rank
            symbol = $symbol
            name = [string]$coin.name
            coin_id = [string]$coin.id
            market_cap_usd = [math]::Round($marketCap, 2)
            price_usd = [math]::Round($price, 10)
        }
    }
}

$derivativeSymbols = @(
    "ALUSD", "BETH", "BTC.B", "BTCB", "CBBTC", "CBETH", "EBTC", "ETHX",
    "FRXETH", "GHO", "JITOSOL", "LBTC", "METH", "MSOL", "OHMV2", "PYUSD",
    "RETH", "RSETH", "SOLVBTC", "STETH", "STKAAVE", "SUSDE", "SUSDS",
    "TBTC", "TETH", "USDAI", "USDC.E", "USDG", "USDF", "USDTB", "WBNB",
    "WBTC", "WEETH", "WETH", "WSTETH", "WTRX"
)
$stableSymbols = @(
    "DAI", "EURC", "FRAX", "LUSD", "STABLE", "TUSD", "USDB", "USDC",
    "USDD", "USDE", "USDF", "USDG", "USDP", "USDT", "USDTB", "USD0",
    "USDX"
)
$derivativeNamePattern = "(?i)(wrapped|staked|restaked|liquid staked|binance-peg|coinbase wrapped|bridged|beacon eth|rocket pool eth|frax ether|treehouse eth|solv protocol|lombard staked|kine?tiq staked|jito staked|marinade staked)"
$stableNamePattern = "(?i)(stablecoin|\busd\b|usd |dollar|paypal usd|euro coin|usual usd|falcon usd|global dollar)"

$focus = foreach ($coin in $fullMissing) {
    $symbol = $coin.symbol.Trim().ToUpperInvariant()
    $isDerivative = ($derivativeSymbols -contains $symbol) -or ($coin.name -match $derivativeNamePattern) -or ($symbol -match "\.")
    $isStable = ($stableSymbols -contains $symbol) -or ($coin.name -match $stableNamePattern)
    if (-not $isDerivative -and -not $isStable) {
        $coin
    }
}

$fullCsv = Join-Path $OutDir "no_binance_full_$DateStamp.csv"
$focusCsv = Join-Path $OutDir "no_binance_focus_$DateStamp.csv"
$symbolsTxt = Join-Path $OutDir "no_binance_focus_symbols_$DateStamp.txt"
$topTxt = Join-Path $OutDir "no_binance_focus_top$TopPreview`_$DateStamp.txt"

$fullMissing | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $fullCsv
$focus | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $focusCsv
$focus | ForEach-Object { $_.symbol } | Set-Content -Encoding UTF8 -Path $symbolsTxt
$focus |
    Select-Object -First $TopPreview |
    ForEach-Object { "{0}`t{1}`t{2}`t{3}" -f $_.rank, $_.symbol, $_.name, $_.coin_id } |
    Set-Content -Encoding UTF8 -Path $topTxt

[PSCustomObject]@{
    binance_assets = $binanceAssets.Keys.Count
    source_ranked_coins = @($ranked).Count
    no_binance_full = @($fullMissing).Count
    no_binance_focus = @($focus).Count
    full_csv = $fullCsv
    focus_csv = $focusCsv
    focus_symbols_txt = $symbolsTxt
    top_preview_txt = $topTxt
} | ConvertTo-Json -Depth 3
