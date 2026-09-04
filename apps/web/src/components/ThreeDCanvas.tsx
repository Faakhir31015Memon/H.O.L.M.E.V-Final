import React, { useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid, Stage, Float } from '@react-three/drei';
import { useHolmevStore } from '../store/useHolmevStore';
import { Box, Plus, RefreshCw, Trash2, Move } from 'lucide-react';

const MeshObject: React.FC<{ obj: any }> = ({ obj }) => {
  return (
    <mesh position={obj.position} scale={obj.scale} rotation={obj.rotation}>
      {obj.type === "cube" && <boxGeometry args={[1.5, 1.5, 1.5]} />}
      {obj.type === "sphere" && <sphereGeometry args={[1, 32, 32]} />}
      {obj.type === "cylinder" && <cylinderGeometry args={[1, 1, 2, 32]} />}
      <meshStandardMaterial
        color={obj.color || "#00f0ff"}
        roughness={0.2}
        metalness={0.8}
        emissive={obj.color || "#00f0ff"}
        emissiveIntensity={0.2}
      />
    </mesh>
  );
};

export const ThreeDCanvas: React.FC = () => {
  const { threeDObjects, addThreeDObject, setThreeDObjects } = useHolmevStore();
  const [selectedType, setSelectedType] = useState<string>("cube");

  const handleAddObject = async () => {
    try {
      const resp = await fetch("/api/v1/brain/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: `Ek ${selectedType} banao` })
      });
      const data = await resp.json();
      if (data?.result?.data?.object) {
        addThreeDObject(data.result.data.object);
      }
    } catch (e) {
      // Local fallback mesh add
      addThreeDObject({
        id: `obj_${Date.now()}`,
        type: selectedType,
        position: [(Math.random() - 0.5) * 3, 0, (Math.random() - 0.5) * 3],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
        color: "#00f0ff"
      });
    }
  };

  const handleClearScene = () => {
    setThreeDObjects([]);
  };

  return (
    <div className="glass-panel rounded-2xl p-6 h-[calc(100vh-8rem)] flex flex-col relative border border-cyber-border">
      <div className="flex items-center justify-between mb-4 z-10">
        <div>
          <h2 className="text-lg font-bold font-mono text-cyan-400 text-glow flex items-center gap-2">
            <Box className="w-5 h-5 text-cyan-400" />
            Interactive 3D Workspace Engine
          </h2>
          <p className="text-xs text-slate-400 font-mono">
            Three.js / React Three Fiber Real-Time Canvas
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="bg-slate-900 border border-cyber-border rounded-xl px-3 py-1.5 font-mono text-xs text-cyan-300 focus:outline-none focus:border-cyan-500"
          >
            <option value="cube">Cube Primitive</option>
            <option value="sphere">Sphere Primitive</option>
            <option value="cylinder">Cylinder Primitive</option>
          </select>

          <button
            onClick={handleAddObject}
            className="flex items-center space-x-1.5 px-4 py-1.5 rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/50 hover:bg-cyan-500/30 text-xs font-mono transition-all shadow-[0_0_15px_rgba(0,240,255,0.25)]"
          >
            <Plus className="w-4 h-4" />
            <span>Add 3D Mesh</span>
          </button>

          <button
            onClick={handleClearScene}
            className="p-1.5 rounded-xl bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 text-xs font-mono transition-all"
            title="Clear 3D Scene"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* R3F Canvas Container */}
      <div className="flex-1 rounded-xl overflow-hidden bg-slate-950/80 border border-slate-800 relative">
        <Canvas camera={{ position: [5, 5, 5], fov: 50 }}>
          <ambientLight intensity={0.5} />
          <pointLight position={[10, 10, 10]} intensity={1.5} />
          <directionalLight position={[-5, 5, 5]} intensity={1} />
          
          <OrbitControls makeDefault minDistance={2} maxDistance={20} />
          <Grid infiniteGrid sectionSize={1} sectionColor="#00f0ff" cellColor="#1e293b" fadeDistance={30} />
          
          <group position={[0, 0, 0]}>
            {threeDObjects.map((obj) => (
              <MeshObject key={obj.id} obj={obj} />
            ))}
          </group>
        </Canvas>

        <div className="absolute bottom-4 left-4 bg-slate-900/80 backdrop-blur border border-slate-800 rounded-lg p-3 text-[11px] font-mono text-slate-300 pointer-events-none">
          <div className="text-cyan-400 font-bold mb-1">3D Controls</div>
          <div>Left Click + Drag: Rotate Camera</div>
          <div>Right Click + Drag: Pan Camera</div>
          <div>Scroll: Zoom Camera</div>
        </div>
      </div>
    </div>
  );
};
