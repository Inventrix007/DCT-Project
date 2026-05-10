// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title DelegationRegistry
 * @notice On-chain audit trail for AI agent delegation chains.
 *         Implements Delegation Capability Tokens (DCTs) based on
 *         "Intelligent AI Delegation" (Tomasev et al., 2026).
 *
 * Core invariant: a delegatee can never grant more authority than
 * they themselves hold (no privilege escalation).
 *
 * Scope ordering: MANAGE(0) is broadest, TEST(2) is narrowest.
 *   MANAGE can sub-delegate to CODE or TEST.
 *   CODE can sub-delegate to TEST only.
 *   TEST cannot sub-delegate at all.
 */
contract DelegationRegistry {

    // -----------------------------------------------------------------
    // Data structures
    // -----------------------------------------------------------------

    enum Scope { MANAGE, CODE, TEST }   // MANAGE(0) broadest, TEST(2) narrowest

    struct DCT {
        uint256 id;
        uint256 parentId;       // 0 = root (human-issued)
        address delegator;
        address delegatee;
        Scope   scope;
        string  taskDescription;
        uint256 issuedAt;
        uint256 expiresAt;      // 0 = no expiry
        bool    revoked;
        bool    completed;
    }

    struct ActionLog {
        uint256 tokenId;
        address agent;
        string  actionType;
        string  details;
        uint256 timestamp;
    }

    // -----------------------------------------------------------------
    // State
    // -----------------------------------------------------------------

    uint256 private _nextId = 1;

    mapping(uint256 => DCT)        public tokens;
    mapping(address => uint256[])  public agentTokens;   // delegatee -> token ids
    mapping(uint256 => uint256[])  public childTokens;   // parentId  -> child token ids
    mapping(uint256 => uint256[])  private _tokenActionIndices; // tokenId -> actionLogs indices
    ActionLog[]                    public actionLogs;

    // -----------------------------------------------------------------
    // Events
    // -----------------------------------------------------------------

    event Delegated(
        uint256 indexed tokenId,
        uint256 indexed parentId,
        address indexed delegator,
        address delegatee,
        Scope   scope,
        string  taskDescription
    );

    event ActionRecorded(
        uint256 indexed tokenId,
        address indexed agent,
        string  actionType,
        string  details,
        uint256 timestamp
    );

    event TokenRevoked(uint256 indexed tokenId, address revokedBy);
    event TokenCompleted(uint256 indexed tokenId, address completedBy);

    // -----------------------------------------------------------------
    // Core functions
    // -----------------------------------------------------------------

    /**
     * @notice Mint a root DCT (represents a human principal starting a pipeline).
     */
    function mintRoot(
        address delegatee,
        Scope   scope,
        string calldata taskDescription,
        uint256 expiresAt
    ) external returns (uint256) {
        uint256 id = _nextId++;
        tokens[id] = DCT({
            id:              id,
            parentId:        0,
            delegator:       msg.sender,
            delegatee:       delegatee,
            scope:           scope,
            taskDescription: taskDescription,
            issuedAt:        block.timestamp,
            expiresAt:       expiresAt,
            revoked:         false,
            completed:       false
        });
        agentTokens[delegatee].push(id);
        childTokens[0].push(id);   // parentId=0 tracks all root tokens

        emit Delegated(id, 0, msg.sender, delegatee, scope, taskDescription);
        return id;
    }

    /**
     * @notice Sub-delegate: caller must hold an active, non-expired token
     *         whose scope is strictly higher (narrower) than what they grant.
     *         Enforces the no-privilege-escalation invariant.
     */
    function delegate(
        uint256 parentTokenId,
        address delegatee,
        Scope   scope,
        string calldata taskDescription,
        uint256 expiresAt
    ) external returns (uint256) {
        DCT storage parent = tokens[parentTokenId];

        require(parent.delegatee == msg.sender,     "Not token holder");
        require(!parent.revoked,                    "Parent token revoked");
        require(!parent.completed,                  "Parent token completed");
        require(
            parent.expiresAt == 0 || block.timestamp < parent.expiresAt,
            "Parent token expired"
        );
        // No privilege escalation: child scope enum value must be strictly larger
        require(uint8(scope) > uint8(parent.scope), "Scope escalation denied");

        uint256 id = _nextId++;
        tokens[id] = DCT({
            id:              id,
            parentId:        parentTokenId,
            delegator:       msg.sender,
            delegatee:       delegatee,
            scope:           scope,
            taskDescription: taskDescription,
            issuedAt:        block.timestamp,
            expiresAt:       expiresAt,
            revoked:         false,
            completed:       false
        });
        agentTokens[delegatee].push(id);
        childTokens[parentTokenId].push(id);

        emit Delegated(id, parentTokenId, msg.sender, delegatee, scope, taskDescription);
        return id;
    }

    /**
     * @notice Record an agent action against their active, non-expired token.
     */
    function recordAction(
        uint256 tokenId,
        string calldata actionType,
        string calldata details
    ) external {
        DCT storage token = tokens[tokenId];
        require(token.delegatee == msg.sender,  "Not token holder");
        require(!token.revoked,                 "Token revoked");
        require(!token.completed,               "Token already completed");
        require(
            token.expiresAt == 0 || block.timestamp < token.expiresAt,
            "Token expired"
        );

        uint256 idx = actionLogs.length;
        actionLogs.push(ActionLog({
            tokenId:    tokenId,
            agent:      msg.sender,
            actionType: actionType,
            details:    details,
            timestamp:  block.timestamp
        }));
        _tokenActionIndices[tokenId].push(idx);

        emit ActionRecorded(tokenId, msg.sender, actionType, details, block.timestamp);
    }

    /**
     * @notice Mark a token complete (called by the token holder on finish).
     */
    function complete(uint256 tokenId) external {
        DCT storage token = tokens[tokenId];
        require(token.delegatee == msg.sender, "Not token holder");
        require(!token.revoked,                "Token revoked");
        token.completed = true;
        emit TokenCompleted(tokenId, msg.sender);
    }

    /**
     * @notice Revoke a token. Callable by delegator or delegatee (self-surrender).
     *         Note: child tokens are NOT auto-revoked; walk childTokens[] if needed.
     */
    function revoke(uint256 tokenId) external {
        DCT storage token = tokens[tokenId];
        require(
            token.delegator == msg.sender || token.delegatee == msg.sender,
            "Not authorized to revoke"
        );
        token.revoked = true;
        emit TokenRevoked(tokenId, msg.sender);
    }

    // -----------------------------------------------------------------
    // View / audit functions
    // -----------------------------------------------------------------

    /**
     * @notice Reconstruct the full delegation chain for a given token.
     *         Returns array ordered root to given token (inclusive).
     */
    function getChain(uint256 tokenId) external view returns (DCT[] memory) {
        uint256 depth = 0;
        uint256 cur = tokenId;
        while (cur != 0) {
            depth++;
            cur = tokens[cur].parentId;
        }
        DCT[] memory chain = new DCT[](depth);
        cur = tokenId;
        for (uint256 i = depth; i > 0; i--) {
            chain[i - 1] = tokens[cur];
            cur = tokens[cur].parentId;
        }
        return chain;
    }

    /**
     * @notice Get direct child token IDs for a given parent (O(1) index lookup).
     *         Pass parentId=0 to list all root tokens.
     */
    function getChildTokens(uint256 parentId) external view returns (uint256[] memory) {
        return childTokens[parentId];
    }

    /**
     * @notice Get all action logs for a specific token.
     *         O(k) where k = number of actions for that token (uses index, not full scan).
     */
    function getTokenActions(uint256 tokenId)
        external view returns (ActionLog[] memory)
    {
        uint256[] storage indices = _tokenActionIndices[tokenId];
        ActionLog[] memory result = new ActionLog[](indices.length);
        for (uint256 i = 0; i < indices.length; i++) {
            result[i] = actionLogs[indices[i]];
        }
        return result;
    }

    /**
     * @notice Get all action logs across all tokens (full audit trail).
     */
    function getAllActions() external view returns (ActionLog[] memory) {
        return actionLogs;
    }

    /**
     * @notice Get all token IDs held by an agent (as delegatee).
     */
    function getAgentTokens(address agent) external view returns (uint256[] memory) {
        return agentTokens[agent];
    }

    function totalTokens() external view returns (uint256) {
        return _nextId - 1;
    }
}
