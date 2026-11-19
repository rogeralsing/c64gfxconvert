// A convex viewport contains the complete edge when it contains both vertices.
// The bounds pass selects this mesh-wide fast path once per frame.
*=$1a00 "In-bounds globe edges"
meshNeedsClip:
    .byte 0
drawInsideMesh:
    .var mesh = LoadBinary("build/globe-mesh.bin")
    .for (var edge = 0; edge < MESH_EDGE_COUNT; edge++) {
        .var a = mesh.get(meshEdgeA - meshVertexX + edge)
        .var b = mesh.get(meshEdgeB - meshVertexX + edge)
        .var left = mesh.get(meshEdgeFaceA - meshVertexX + edge)
        .var right = mesh.get(meshEdgeFaceB - meshVertexX + edge)
        lda meshVisibleFaces + left
        ora meshVisibleFaces + right
        beq !next+
        lda PTAB + a
        sta lx0
        lda PTAB + a + 1
        sta ly0
        ldx #b
        jsr drawInsideMeshEdge
    !next:
    }
    rts

drawInsideMeshEdge:
    lda PTAB,x
    sta lx1
    lda PTAB+1,x
    sta ly1
    jmp drawCharLine
.assert "In-bounds globe edges fit below the character bank", * <= CHARSET, true
