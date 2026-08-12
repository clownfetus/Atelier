// Copyright 2019-2026 pafuhana1213. All Rights Reserved.

#include "KawaiiPhysicsLibrary.h"

#if ENGINE_MAJOR_VERSION >= 5 && ENGINE_MINOR_VERSION >= 6
#include "Animation/AnimInstance.h"
#endif

#include "AnimNode_KawaiiPhysics.h"
#include "BlueprintGameplayTagLibrary.h"
#include "ExternalForces/KawaiiPhysicsExternalForce.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(KawaiiPhysicsLibrary)

DEFINE_LOG_CATEGORY_STATIC(LogKawaiiPhysicsLibrary, Verbose, All);

FKawaiiPhysicsReference UKawaiiPhysicsLibrary::ConvertToKawaiiPhysics(const FAnimNodeReference& Node,
                                                                      EAnimNodeReferenceConversionResult& Result)
{
	return FAnimNodeReference::ConvertToType<FKawaiiPhysicsReference>(Node, Result);
}

bool UKawaiiPhysicsLibrary::CollectKawaiiPhysicsNodes(TArray<FKawaiiPhysicsReference>& Nodes,
                                                      UAnimInstance* AnimInstance,
                                                      const FGameplayTagContainer& FilterTags, bool bFilterExactMatch)
{
	if (!ensure(AnimInstance && AnimInstance->GetClass()))
	{
		return false;
	}

	bool bResult = false;
	if (const IAnimClassInterface* AnimClassInterface =
		IAnimClassInterface::GetFromClass((AnimInstance->GetClass())))
	{
		const TArray<FStructProperty*>& AnimNodeProperties = AnimClassInterface->GetAnimNodeProperties();
		for (int i = 0; i < AnimNodeProperties.Num(); ++i)
		{
			if (AnimNodeProperties[i]->Struct->
			                           IsChildOf(FKawaiiPhysicsReference::FInternalNodeType::StaticStruct()))
			{
				EAnimNodeReferenceConversionResult Result;
				FKawaiiPhysicsReference KawaiiPhysicsReference = ConvertToKawaiiPhysics(
					FAnimNodeReference(AnimInstance, i), Result);

				if (Result == EAnimNodeReferenceConversionResult::Succeeded)
				{
					auto& Tag = KawaiiPhysicsReference.GetAnimNode<FAnimNode_KawaiiPhysics>().KawaiiPhysicsTag;
					if (FilterTags.IsEmpty() || UBlueprintGameplayTagLibrary::MatchesAnyTags(
						Tag, FilterTags, bFilterExactMatch))
					{
						Nodes.Add(KawaiiPhysicsReference);
						bResult = true;
					}
				}
			}
		}
	}

	return bResult;
}

bool UKawaiiPhysicsLibrary::CollectKawaiiPhysicsNodes(TArray<FKawaiiPhysicsReference>& Nodes,
                                                      USkeletalMeshComponent* MeshComp,
                                                      const FGameplayTagContainer& FilterTags, bool bFilterExactMatch)
{
	if (!ensure(MeshComp))
	{
		return false;
	}

	const int NodeNum = Nodes.Num();

	if (UAnimInstance* AnimInstance = MeshComp->GetAnimInstance())
	{
		CollectKawaiiPhysicsNodes(Nodes, AnimInstance, FilterTags,
		                          bFilterExactMatch);
	}

	const TArray<UAnimInstance*>& LinkedInstances =
		const_cast<const USkeletalMeshComponent*>(MeshComp)->GetLinkedAnimInstances();
	for (UAnimInstance* LinkedInstance : LinkedInstances)
	{
		CollectKawaiiPhysicsNodes(Nodes, LinkedInstance, FilterTags,
		                          bFilterExactMatch);
	}

	if (UAnimInstance* PostProcessAnimInstance = MeshComp->GetPostProcessInstance())
	{
		CollectKawaiiPhysicsNodes(Nodes, PostProcessAnimInstance, FilterTags,
		                          bFilterExactMatch);
	}

	return NodeNum != Nodes.Num();
}

FKawaiiPhysicsReference UKawaiiPhysicsLibrary::ResetDynamics(const FKawaiiPhysicsReference& KawaiiPhysics)
{
	KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
		TEXT("ResetDynamics"),
		[](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
		{
			InKawaiiPhysics.ResetDynamics(ETeleportType::ResetPhysics);
		});

	return KawaiiPhysics;
}


FKawaiiPhysicsReference UKawaiiPhysicsLibrary::SetRootBoneName(const FKawaiiPhysicsReference& KawaiiPhysics,
                                                               FName& RootBoneName, int32 ChainIndex)
{
	KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
		TEXT("SetRootBoneName"),
		[RootBoneName, ChainIndex](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
		{
			if (InKawaiiPhysics.Chains.IsValidIndex(ChainIndex))
			{
				InKawaiiPhysics.Chains[ChainIndex].BoneSettings.RootBone = FBoneReference(RootBoneName);
			}
			else
			{
				InKawaiiPhysics.RootBone = FBoneReference(RootBoneName);
			}
		});

	return KawaiiPhysics;
}

FName UKawaiiPhysicsLibrary::GetRootBoneName(const FKawaiiPhysicsReference& KawaiiPhysics, int32 ChainIndex)
{
	FName RootBoneName;

	KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
		TEXT("GetRootBoneName"),
		[&RootBoneName, ChainIndex](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
		{
			if (InKawaiiPhysics.Chains.IsValidIndex(ChainIndex))
			{
				RootBoneName = InKawaiiPhysics.Chains[ChainIndex].BoneSettings.RootBone.BoneName;
			}
			else
			{
				RootBoneName = InKawaiiPhysics.RootBone.BoneName;
			}
		});

	return RootBoneName;
}

FKawaiiPhysicsReference UKawaiiPhysicsLibrary::SetExcludeBoneNames(const FKawaiiPhysicsReference& KawaiiPhysics,
                                                                   TArray<FName>& ExcludeBoneNames, int32 ChainIndex)
{
	KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
		TEXT("SetExcludeBoneNames"),
		[&ExcludeBoneNames, ChainIndex](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
		{
			if (InKawaiiPhysics.Chains.IsValidIndex(ChainIndex))
			{
				InKawaiiPhysics.Chains[ChainIndex].BoneSettings.ExcludeBones.Empty();
				for (auto& ExcludeBoneName : ExcludeBoneNames)
				{
					InKawaiiPhysics.Chains[ChainIndex].BoneSettings.ExcludeBones.Add(FBoneReference(ExcludeBoneName));
				}
			}
			else
			{
				InKawaiiPhysics.ExcludeBones.Empty();
				for (auto& ExcludeBoneName : ExcludeBoneNames)
				{
					InKawaiiPhysics.ExcludeBones.Add(FBoneReference(ExcludeBoneName));
				}
			}
		});

	return KawaiiPhysics;
}

TArray<FName> UKawaiiPhysicsLibrary::GetExcludeBoneNames(const FKawaiiPhysicsReference& KawaiiPhysics, int32 ChainIndex)
{
	TArray<FName> ExcludeBoneNames;

	KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
		TEXT("GetExcludeBoneNames"),
		[&ExcludeBoneNames, ChainIndex](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
		{
			if (InKawaiiPhysics.Chains.IsValidIndex(ChainIndex))
			{
				for (auto& ExcludeBone : InKawaiiPhysics.Chains[ChainIndex].BoneSettings.ExcludeBones)
				{
					ExcludeBoneNames.Add(ExcludeBone.BoneName);
				}
			}
			else
			{
				for (auto& ExcludeBone : InKawaiiPhysics.ExcludeBones)
				{
					ExcludeBoneNames.Add(ExcludeBone.BoneName);
				}
			}
		});

	return ExcludeBoneNames;
}

FKawaiiPhysicsReference UKawaiiPhysicsLibrary::AddExternalForceWithExecResult(
	EKawaiiPhysicsAccessExternalForceResult& ExecResult,
	const FKawaiiPhysicsReference& KawaiiPhysics,
	FInstancedStruct& ExternalForce, UObject* Owner, int32 ChainIndex)
{
	ExecResult = EKawaiiPhysicsAccessExternalForceResult::NotValid;

	if (AddExternalForce(KawaiiPhysics, ExternalForce, Owner, false, ChainIndex))
	{
		ExecResult = EKawaiiPhysicsAccessExternalForceResult::Valid;
	}

	return KawaiiPhysics;
}

bool UKawaiiPhysicsLibrary::AddExternalForce(const FKawaiiPhysicsReference& KawaiiPhysics,
                                             FInstancedStruct& ExternalForce, UObject* Owner, bool bIsOneShot, int32 ChainIndex)
{
	bool bResult = false;

	if (ExternalForce.IsValid())
	{
		if (auto* ExternalForcePtr = ExternalForce.GetMutablePtr<FKawaiiPhysics_ExternalForce>())
		{
			ExternalForcePtr->ExternalOwner = Owner;
			ExternalForcePtr->bIsOneShot = bIsOneShot;

			KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
				TEXT("AddExternalForce"),
				[&, ChainIndex](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
				{
					if (InKawaiiPhysics.Chains.IsValidIndex(ChainIndex))
					{
						InKawaiiPhysics.Chains[ChainIndex].ExternalForceSettings.ExternalForces.Add(ExternalForce);
					}
					else
					{
						InKawaiiPhysics.ExternalForces.Add(ExternalForce);
					}
				});

			bResult = true;
		}
	}

	return bResult;
}

bool UKawaiiPhysicsLibrary::AddExternalForcesToComponent(USkeletalMeshComponent* MeshComp,
                                                         TArray<FInstancedStruct>& ExternalForces,
                                                         UObject* Owner,
                                                         FGameplayTagContainer& FilterTags,
                                                         bool bFilterExactMatch, bool bIsOneShot)
{
	bool bResult = false;

	TArray<FKawaiiPhysicsReference> KawaiiPhysicsReferences;
	CollectKawaiiPhysicsNodes(KawaiiPhysicsReferences, MeshComp, FilterTags, bFilterExactMatch);
	for (auto& KawaiiPhysicsReference : KawaiiPhysicsReferences)
	{
		for (auto& AExternalForce : ExternalForces)
		{
			if (AExternalForce.IsValid())
			{
				if (AddExternalForce(KawaiiPhysicsReference, AExternalForce, Owner, bIsOneShot))
				{
					bResult = true;
				}
			}
		}
	}

	return bResult;
}

bool UKawaiiPhysicsLibrary::RemoveExternalForcesFromComponent(USkeletalMeshComponent* MeshComp, UObject* Owner,
                                                              FGameplayTagContainer& FilterTags, bool bFilterExactMatch)
{
	bool bResult = false;

	TArray<FKawaiiPhysicsReference> KawaiiPhysicsReferences;
	CollectKawaiiPhysicsNodes(KawaiiPhysicsReferences, MeshComp, FilterTags, bFilterExactMatch);
	for (auto& KawaiiPhysicsReference : KawaiiPhysicsReferences)
	{
		KawaiiPhysicsReference.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
			TEXT("RemoveExternalForce"),
			[&](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
			{
				const int32 NumRemoved = InKawaiiPhysics.ExternalForces.RemoveAll([&](FInstancedStruct& InstancedStruct)
				{
					const auto* ExternalForcePtr = InstancedStruct.GetMutablePtr<FKawaiiPhysics_ExternalForce>();
					return ExternalForcePtr && ExternalForcePtr->ExternalOwner == Owner;
				});

				if (NumRemoved > 0)
				{
					bResult = true;
				}

				for (auto& Chain : InKawaiiPhysics.Chains)
				{
					const int32 NumRemovedChain = Chain.ExternalForceSettings.ExternalForces.RemoveAll(
						[&](FInstancedStruct& InstancedStruct)
					{
						const auto* ExternalForcePtr = InstancedStruct.GetMutablePtr<FKawaiiPhysics_ExternalForce>();
						return ExternalForcePtr && ExternalForcePtr->ExternalOwner == Owner;
					});

					if (NumRemovedChain > 0)
					{
						bResult = true;
					}
				}
			});
	}

	return bResult;
}

bool UKawaiiPhysicsLibrary::SetAlphaToComponent(USkeletalMeshComponent* MeshComp, float Alpha,
                                                FGameplayTagContainer& FilterTags, bool bFilterExactMatch)
{
	bool bResult = false;

	TArray<FKawaiiPhysicsReference> KawaiiPhysicsReferences;
	CollectKawaiiPhysicsNodes(KawaiiPhysicsReferences, MeshComp, FilterTags, bFilterExactMatch);
	for (auto& KawaiiPhysicsReference : KawaiiPhysicsReferences)
	{
		KawaiiPhysicsReference.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
			TEXT("SetAlpha"),
			[&](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
			{
				InKawaiiPhysics.Alpha = Alpha;
				bResult = true;
			});
	}

	return bResult;
}

bool UKawaiiPhysicsLibrary::GetAlphaFromComponent(USkeletalMeshComponent* MeshComp, float& OutAlpha,
                                                  FGameplayTagContainer& FilterTags, bool bFilterExactMatch)
{
	bool bResult = false;
	OutAlpha = 0.0f;

	TArray<FKawaiiPhysicsReference> KawaiiPhysicsReferences;
	CollectKawaiiPhysicsNodes(KawaiiPhysicsReferences, MeshComp, FilterTags, bFilterExactMatch);
	for (auto& KawaiiPhysicsReference : KawaiiPhysicsReferences)
	{
		KawaiiPhysicsReference.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
			TEXT("GetAlpha"),
			[&](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
			{
				OutAlpha = InKawaiiPhysics.Alpha;
				bResult = true;
			});
		if (bResult)
		{
			break;
		}
	}

	return bResult;
}

DEFINE_FUNCTION(UKawaiiPhysicsLibrary::execSetExternalForceWildcardProperty)
{
	P_GET_ENUM_REF(EKawaiiPhysicsAccessExternalForceResult, ExecResult);
	P_GET_STRUCT_REF(FKawaiiPhysicsReference, KawaiiPhysics);
	P_GET_PROPERTY(FIntProperty, ExternalForceIndex);
	P_GET_STRUCT_REF(FName, PropertyName);
	P_GET_PROPERTY(FIntProperty, ChainIndex);

	ExecResult = EKawaiiPhysicsAccessExternalForceResult::NotValid;

	// Read wildcard Value input.
	Stack.MostRecentPropertyAddress = nullptr;
	Stack.MostRecentPropertyContainer = nullptr;
	Stack.StepCompiledIn<FStructProperty>(nullptr);

	const FProperty* ValueProp = CastField<FProperty>(Stack.MostRecentProperty);
	void* ValuePtr = Stack.MostRecentPropertyAddress;

	KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
		TEXT("GetExternalForceWildcardProperty"),
		[&ExecResult, &ExternalForceIndex, &PropertyName, &ValuePtr, ChainIndex](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
		{
			TArray<FInstancedStruct>* ExternalForces = &InKawaiiPhysics.ExternalForces;
			if (InKawaiiPhysics.Chains.IsValidIndex(ChainIndex))
			{
				ExternalForces = &InKawaiiPhysics.Chains[ChainIndex].ExternalForceSettings.ExternalForces;
			}
			if (ExternalForces->IsValidIndex(ExternalForceIndex) &&
				(*ExternalForces)[ExternalForceIndex].IsValid())
			{
				const auto* ScriptStruct = (*ExternalForces)[ExternalForceIndex].GetScriptStruct();
				auto& Force = (*ExternalForces)[ExternalForceIndex].GetMutable<
					FKawaiiPhysics_ExternalForce>();

				if (const FProperty* Property = FindFProperty<FProperty>(ScriptStruct, PropertyName))
				{
					Property->CopyCompleteValue(Property->ContainerPtrToValuePtr<uint8>(&Force), ValuePtr);
					ExecResult = EKawaiiPhysicsAccessExternalForceResult::Valid;
				}
			}
		});

	P_FINISH;
}

DEFINE_FUNCTION(UKawaiiPhysicsLibrary::execGetExternalForceWildcardProperty)
{
	P_GET_ENUM_REF(EKawaiiPhysicsAccessExternalForceResult, ExecResult);
	P_GET_STRUCT_REF(FKawaiiPhysicsReference, KawaiiPhysics);
	P_GET_PROPERTY(FIntProperty, ExternalForceIndex);
	P_GET_STRUCT_REF(FName, PropertyName);
	P_GET_PROPERTY(FIntProperty, ChainIndex);

	ExecResult = EKawaiiPhysicsAccessExternalForceResult::NotValid;

	// Read wildcard Value input.
	Stack.MostRecentPropertyAddress = nullptr;
	Stack.MostRecentPropertyContainer = nullptr;
	Stack.StepCompiledIn<FStructProperty>(nullptr);

	const FProperty* ValueProp = CastField<FProperty>(Stack.MostRecentProperty);
	void* ValuePtr = Stack.MostRecentPropertyAddress;

	void* Result = nullptr;
	KawaiiPhysics.CallAnimNodeFunction<FAnimNode_KawaiiPhysics>(
		TEXT("GetExternalForceWildcardProperty"),
		[&Result, &ExecResult, &ExternalForceIndex, &PropertyName, ChainIndex](FAnimNode_KawaiiPhysics& InKawaiiPhysics)
		{
			TArray<FInstancedStruct>* ExternalForces = &InKawaiiPhysics.ExternalForces;
			if (InKawaiiPhysics.Chains.IsValidIndex(ChainIndex))
			{
				ExternalForces = &InKawaiiPhysics.Chains[ChainIndex].ExternalForceSettings.ExternalForces;
			}
			if (ExternalForces->IsValidIndex(ExternalForceIndex) &&
				(*ExternalForces)[ExternalForceIndex].IsValid())
			{
				const auto* ScriptStruct = (*ExternalForces)[ExternalForceIndex].GetScriptStruct();
				auto& Force = (*ExternalForces)[ExternalForceIndex].GetMutable<
					FKawaiiPhysics_ExternalForce>();

				if (const FProperty* Property = FindFProperty<FProperty>(ScriptStruct, PropertyName))
				{
					Result = Property->ContainerPtrToValuePtr<void>(&Force);
					ExecResult = EKawaiiPhysicsAccessExternalForceResult::Valid;
				}
			}
		});

	P_FINISH;

	if (ValuePtr && Result)
	{
		P_NATIVE_BEGIN;
			ValueProp->CopyCompleteValue(ValuePtr, Result);
		P_NATIVE_END;
	}
}
