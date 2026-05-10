require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();
// Load from environment — never hardcode keys
const DEPLOYER_PRIVATE_KEY = process.env.DEPLOYER_PRIVATE_KEY || "0x0000000000000000000000000000000000000000000000000000000000000001";
const SEPOLIA_RPC_URL      = process.env.SEPOLIA_RPC_URL      || "";

module.exports = {
  solidity: "0.8.20",
  networks: {
    // Local Hardhat node (instant, free, no real ETH needed)
    hardhat: {
      chainId: 31337,
      mining: { auto: true }
    },
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 31337,
    },
    // Sepolia testnet (real public blockchain, free testnet ETH)
    sepolia: {
      url: SEPOLIA_RPC_URL,
      accounts: [DEPLOYER_PRIVATE_KEY],
      chainId: 11155111,
      gasPrice: "auto",
    }
  },
  etherscan: {
    // Optional: lets you verify contract source on Etherscan
    apiKey: process.env.ETHERSCAN_API_KEY || ""
  }
};
