using System.Text.Json;
using System.Numerics;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using CUE4Parse_Conversion.Animations;
using CUE4Parse_Conversion.Meshes.glTF;

namespace Atelier.Native;

// Decode a real, non-additive animation with the same CUE4Parse build as AtelierMesh.
// Coordinates deliberately use its glTF conversion, including centimetres to metres.
// Ported verbatim from tools-src/AtelierAnimation; only the provider setup is shared now.
static class AnimationCommand
{
    public static int Run(string[] args)
    {
        try
        {
            var options = GameProvider.Options(args);
            using var provider = GameProvider.Open(options["paks"], options["aes"], options["usmap"]);
            var mesh = provider.LoadPackageObject(options["mesh"]) as USkeletalMesh
                ?? throw new InvalidOperationException("Idle playback requires a skeletal mesh");
            var animation = provider.LoadPackageObject(options["animation"]) as UAnimSequence
                ?? throw new InvalidOperationException("Choose an animation sequence");
            var set = animation.ConvertAnims();
            var sequence = set.Sequences.First();
            if (sequence.IsAdditive) throw new InvalidOperationException("Additive clips require their base animation");
            var boneInfo = set.Skeleton.ReferenceSkeleton.FinalRefBoneInfo;
            var meshBones = mesh.ReferenceSkeleton.FinalRefBoneInfo;
            var meshParents = meshBones.ToDictionary(b=>b.Name.Text, b=>b.ParentIndex<0 ? "" : meshBones[b.ParentIndex].Name.Text);
            // An idle may be shared by skins, but must share their actual bone hierarchy.
            var animated = Enumerable.Range(0,Math.Min(sequence.Tracks.Count,boneInfo.Length))
                .Where(i=>sequence.Tracks[i].KeyQuat.Length>1 || sequence.Tracks[i].KeyPos.Length>1 || sequence.Tracks[i].KeyScale.Length>1).ToArray();
            var shared = animated.Where(i=>meshParents.ContainsKey(boneInfo[i].Name.Text)).ToArray();
            var mismatches = shared.Where(i=>meshParents[boneInfo[i].Name.Text] != (boneInfo[i].ParentIndex<0 ? "" : boneInfo[boneInfo[i].ParentIndex].Name.Text)).ToArray();
            if (shared.Length - mismatches.Length < 8 || shared.Length - mismatches.Length < meshBones.Length*.5)
                throw new InvalidOperationException($"Animation skeleton is incompatible: {shared.Length}/{animated.Length} shared animated bones; parents: {string.Join(',',mismatches.Take(5).Select(i=>boneInfo[i].Name.Text))}");
            var compatibleBones = boneInfo.Where(b => meshParents.TryGetValue(b.Name.Text,out var parent)
                && parent == (b.ParentIndex<0 ? "" : boneInfo[b.ParentIndex].Name.Text)).Select(b=>b.Name.Text).ToHashSet();
            if (sequence.NumFrames<2 || sequence.NumFrames>3600 || sequence.FramesPerSecond<=0)
                throw new InvalidOperationException("Invalid or oversized idle sequence");
            var times = Enumerable.Range(0,sequence.NumFrames).Select(i=>i/sequence.FramesPerSecond).ToArray();
            Vector3 V(FVector v) => new(v.X,v.Z,v.Y);
            Quaternion Q(FQuat q) => Quaternion.Normalize(new(q.X,q.Z,q.Y,q.W));
            Matrix4x4 TRS(Vector3 p,Quaternion q,Vector3 s) => Matrix4x4.CreateScale(s)*Matrix4x4.CreateFromQuaternion(q)*Matrix4x4.CreateTranslation(p);
            var meshPoses=mesh.ReferenceSkeleton.FinalRefBonePose;
            var sourcePoses=sequence.RetargetBasePose ?? set.Skeleton.ReferenceSkeleton.FinalRefBonePose;
            var sourceIndices=Enumerable.Range(0,boneInfo.Length).Where(i=>meshParents.ContainsKey(boneInfo[i].Name.Text)).ToDictionary(i=>boneInfo[i].Name.Text);
            int count=meshBones.Length;
            var exportedReference=new Matrix4x4[count]; var physicalReference=new Matrix4x4[count]; var inversePhysicalReference=new Matrix4x4[count];
            // AtelierMesh's exported skeleton swaps Y/Z without conjugating rotations. Its inverse bind
            // matrices compensate in rest pose. Animate in the physical basis, then carry world-space
            // deformation back through those exact exported bind matrices, including skin-only bones.
            for(int bone=0;bone<count;bone++) {
                int parent=meshBones[bone].ParentIndex; var p=V(meshPoses[bone].Translation)*.01f; var q=Q(meshPoses[bone].Rotation);
                exportedReference[bone]=TRS(p,q,Vector3.One)*(parent<0 ? Matrix4x4.Identity : exportedReference[parent]);
                physicalReference[bone]=TRS(p,Quaternion.Inverse(q),Vector3.One)*(parent<0 ? Matrix4x4.Identity : physicalReference[parent]);
                if(!Matrix4x4.Invert(physicalReference[bone],out inversePhysicalReference[bone])) throw new InvalidOperationException("Singular reference skeleton");
            }
            var sourceReference=new Matrix4x4[boneInfo.Length]; var inverseSourceReference=new Matrix4x4[boneInfo.Length];
            var sourcePositions=new FVector[boneInfo.Length];
            for(int bone=0;bone<boneInfo.Length;bone++) {
                int parent=boneInfo[bone].ParentIndex; var pose=sourcePoses[bone]; var position=pose.Translation;
                position.Scale(set.Skeleton.ReferenceSkeleton.GetBoneScale(sourcePoses,bone)); sourcePositions[bone]=position;
                sourceReference[bone]=TRS(V(position)*.01f,Quaternion.Inverse(Q(pose.Rotation)),Vector3.One)*(parent<0?Matrix4x4.Identity:sourceReference[parent]);
                if(!Matrix4x4.Invert(sourceReference[bone],out inverseSourceReference[bone])) throw new InvalidOperationException("Singular source skeleton");
            }
            var positions=Enumerable.Range(0,count).Select(_=>new List<float>()).ToArray();
            var rotations=Enumerable.Range(0,count).Select(_=>new List<float>()).ToArray();
            var scales=Enumerable.Range(0,count).Select(_=>new List<float>()).ToArray();
            for(int frame=0;frame<sequence.NumFrames;frame++) {
                var sourceAnimated=new Matrix4x4[boneInfo.Length];
                for(int bone=0;bone<boneInfo.Length;bone++) {
                    int parent=boneInfo[bone].ParentIndex; var pose=sourcePoses[bone];
                    var position=sourcePositions[bone]; var rotation=pose.Rotation; var scale=pose.Scale3D;
                    if(bone<sequence.Tracks.Count) sequence.Tracks[bone].GetBoneTransform(frame,sequence.NumFrames,ref rotation,ref position,ref scale);
                    sourceAnimated[bone]=TRS(V(position)*.01f,Quaternion.Inverse(Q(rotation)),Vector3.One)*(parent<0?Matrix4x4.Identity:sourceAnimated[parent]);
                }
                var physical=new Matrix4x4[count]; var exported=new Matrix4x4[count];
                for(int bone=0;bone<count;bone++) {
                    int parent=meshBones[bone].ParentIndex; var targetPose=meshPoses[bone];
                    var p=V(targetPose.Translation)*.01f; var q=Quaternion.Inverse(Q(targetPose.Rotation)); var s=Vector3.One;
                    if(sourceIndices.TryGetValue(meshBones[bone].Name.Text,out int sourceBone) && sourceBone<sequence.Tracks.Count) {
                        // World-space deltas also handle weapon bones reparented between the shared
                        // animation skeleton and a skin's exported mesh, without detaching the weapon.
                        physical[bone]=physicalReference[bone]*inverseSourceReference[sourceBone]*sourceAnimated[sourceBone];
                    } else physical[bone]=TRS(p,q,s)*(parent<0?Matrix4x4.Identity:physical[parent]);
                    exported[bone]=exportedReference[bone]*inversePhysicalReference[bone]*physical[bone];
                    var local=exported[bone];
                    if(parent>=0) { if(!Matrix4x4.Invert(exported[parent],out var inverseParent)) throw new InvalidOperationException("Singular animated skeleton"); local*=inverseParent; }
                    if(!Matrix4x4.Decompose(local,out var ls,out var lq,out var lp)) throw new InvalidOperationException("Invalid animated transform");
                    positions[bone].AddRange([lp.X,lp.Y,lp.Z]); rotations[bone].AddRange([lq.X,lq.Y,lq.Z,lq.W]); scales[bone].AddRange([ls.X,ls.Y,ls.Z]);
                }
            }
            var tracks=Enumerable.Range(0,count).Select(bone=>new {bone=meshBones[bone].Name.Text,times,positions=positions[bone],rotations=rotations[bone],scales=scales[bone]}).ToArray();
            var result = new {version=2, space="atelier-gltf-local", name=animation.Name, duration=sequence.NumFrames/sequence.FramesPerSecond,
                source=options["animation"], skeleton=mesh.Skeleton.ToString(), tracks};
            var target=Path.GetFullPath(options["out"]); Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.WriteAllText(target,JsonSerializer.Serialize(result));
            Console.WriteLine($"OK {animation.Name}: {tracks.Length} tracks, {sequence.NumFrames} frames");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
    }
}
