const { ethers } = require("hardhat");
const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deploying with:", deployer.address);

  const Registry = await ethers.getContractFactory("DelegationRegistry");
  const registry = await Registry.deploy();
  await registry.waitForDeployment();

  const address = await registry.getAddress();
  console.log("DelegationRegistry deployed to:", address);

  // Export ABI + address for Python agents to consume
  const artifact = JSON.parse(
    fs.readFileSync(
      path.join(__dirname, "../artifacts/contracts/DelegationRegistry.sol/DelegationRegistry.json")
    )
  );

  const exportDir = path.join(__dirname, "../abi");
  fs.mkdirSync(exportDir, { recursive: true });

  fs.writeFileSync(
    path.join(exportDir, "DelegationRegistry.json"),
    JSON.stringify({ address, abi: artifact.abi }, null, 2)
  );

  // Also write deployer private key for local dev use by Python agents
  const accounts = await ethers.getSigners();
  const keys = {
    deployer:  { address: accounts[0].address },
    manager:   { address: accounts[1].address },
    coder:     { address: accounts[2].address },
    tester:    { address: accounts[3].address },
  };
  fs.writeFileSync(
    path.join(exportDir, "accounts.json"),
    JSON.stringify(keys, null, 2)
  );

  console.log("ABI + addresses written to /abi/");
  console.log("Accounts:", keys);
}

main().catch((e) => { console.error(e); process.exit(1); });
