# Sepolia Testnet Setup Guide

Step-by-step guide to deploy the DCT project on Sepolia — a real public Ethereum
testnet. Your contract and audit trail will be publicly visible on Etherscan.

---

## Step 1 — Get a Sepolia RPC URL (Alchemy)

Alchemy gives you a free node endpoint so you can talk to Sepolia without
running your own node.

1. Go to https://alchemy.com and create a free account
2. Click **"Create App"**
3. Name it anything (e.g. "DCT Project"), select **Ethereum**, select **Sepolia**
4. Click your app → **"API Key"** → copy the **HTTPS** URL

It will look like:
```
https://eth-sepolia.g.alchemy.com/v2/abc123yourkey
```

Save this. You'll use it as `SEPOLIA_RPC_URL`.

---

## Step 2 — Create 4 wallets

You need 4 separate Ethereum wallets: Deployer, Manager, Coder, Tester.
These represent distinct on-chain identities — the whole point of DCTs.

**Option A: Generate with Python (recommended, no MetaMask needed)**

```bash
python3 - << 'EOF'
from eth_account import Account
import json

roles = ['deployer', 'manager', 'coder', 'tester']
for role in roles:
    acct = Account.create()
    print(f"\n{role.upper()}")
    print(f"  Address:     {acct.address}")
    print(f"  Private key: {acct.key.hex()}")
EOF
```

**Option B: MetaMask**
- Open MetaMask → click your account icon → "Add account" × 4
- Export each private key: Account Details → "Show private key"

⚠️ Save all 4 addresses and private keys somewhere safe.
   These are test wallets — never put real ETH in them.

---

## Step 3 — Fund wallets with Sepolia ETH (free)

You need Sepolia ETH for gas. Only the **Deployer** wallet needs a meaningful
amount (~0.1 SepoliaETH). The others need a tiny amount (~0.01 each).

**Faucets (pick any):**
- https://sepoliafaucet.com (Alchemy — requires Alchemy account, gives 0.5/day)
- https://faucet.sepolia.dev (no account needed, smaller amount)
- https://www.infura.io/faucet/sepolia (requires Infura account)

Fund the **Deployer** first (it pays for the contract deployment).
Then send a small amount from Deployer to Manager, Coder, and Tester
so they can pay for their own transactions.

**Rough gas cost estimates per run:**
- Contract deployment: ~0.002 SepoliaETH
- Each `mintRoot` / `delegate`: ~0.0005 SepoliaETH
- Each `recordAction`: ~0.0003 SepoliaETH
- Full pipeline (all agents): ~0.005 SepoliaETH total

---

## Step 4 — Set environment variables

Create a `.env` file in your project root (never commit this to git):

```bash
# .env
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_ALCHEMY_KEY

# Deployer (pays for contract deployment)
DEPLOYER_PRIVATE_KEY=0xYOUR_DEPLOYER_PRIVATE_KEY
DEPLOYER_ADDRESS=0xYOUR_DEPLOYER_ADDRESS

# Manager Agent
MANAGER_PRIVATE_KEY=0xYOUR_MANAGER_PRIVATE_KEY
MANAGER_ADDRESS=0xYOUR_MANAGER_ADDRESS

# Coder Agent
CODER_PRIVATE_KEY=0xYOUR_CODER_PRIVATE_KEY
CODER_ADDRESS=0xYOUR_CODER_ADDRESS

# Tester Agent
TESTER_PRIVATE_KEY=0xYOUR_TESTER_PRIVATE_KEY
TESTER_ADDRESS=0xYOUR_TESTER_ADDRESS

# LLM
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY
```

Add `.env` to your `.gitignore`:
```bash
echo ".env" >> .gitignore
```

Load them before running:
```bash
export $(cat .env | xargs)
```

---

## Step 5 — Deploy the contract to Sepolia

```bash
NETWORK=sepolia npx hardhat run scripts/deploy.cjs --network sepolia
```

This will:
- Compile `DelegationRegistry.sol`
- Deploy it to Sepolia (takes ~15–30 seconds)
- Write the contract address + ABI to `abi/DelegationRegistry.json`
- Print the contract address

You'll see something like:
```
Deploying with: 0x280cCbCA37...
DelegationRegistry deployed to: 0xABCD1234...
ABI + addresses written to /abi/
```

**View your deployed contract:**
```
https://sepolia.etherscan.io/address/0xYOUR_CONTRACT_ADDRESS
```

---

## Step 6 — Run the pipeline

```bash
export $(cat .env | xargs)
NETWORK=sepolia python agents/run_pipeline.py
```

You'll see each agent's LLM calls and each on-chain transaction print as they
happen. Each `[chain]` line is a real Sepolia transaction being confirmed.

**After it finishes**, go to Etherscan and click the **"Events"** tab on your
contract address — you'll see every `Delegated` and `ActionRecorded` event
with full on-chain data. That's your tamper-proof audit trail.

---

## Step 7 — (Optional) Verify contract source on Etherscan

This makes your contract code publicly readable on Etherscan, which is great
for a project submission.

1. Get a free Etherscan API key at https://etherscan.io/apis
2. Add to your `.env`: `ETHERSCAN_API_KEY=YOUR_KEY`
3. Run:
```bash
npx hardhat verify --network sepolia 0xYOUR_CONTRACT_ADDRESS
```

---

## Switching between local and Sepolia

```bash
# Local Hardhat (instant, no gas cost)
python agents/run_pipeline.py

# Sepolia (real chain, ~30s per tx)
NETWORK=sepolia python agents/run_pipeline.py
```

The codebase is identical — only the RPC URL and private keys differ.

---

## Troubleshooting

**"insufficient funds"** — Your deployer wallet needs more Sepolia ETH. Hit the faucet again.

**"nonce too high"** — Reset your account nonce in MetaMask: Settings → Advanced → Reset Account. Or just wait a minute and retry.

**"cannot connect to node"** — Check your `SEPOLIA_RPC_URL` is correct and your Alchemy app is set to Sepolia not Mainnet.

**Transaction stuck pending** — Sepolia can get congested. Set `gasPrice` higher in `hardhat.config.cjs` or just wait.

**"replacement transaction underpriced"** — You sent two transactions with the same nonce. Wait for the first to confirm, then retry.
